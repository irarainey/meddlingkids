"""
Individual overlay-handling sub-steps.

Pure functions and coroutines for each stage of the overlay
detect → validate → click → extract flow.  Consumed by
:class:`~src.pipeline.overlay_pipeline.OverlayPipeline`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from playwright import async_api

from src.agents import consent_extraction_agent
from src.browser import session as browser_session
from src.consent import click, constants, extraction, overlay_cache, partner_classification
from src.consent import detection as consent_detection_mod
from src.models import consent
from src.pipeline import sse_helpers
from src.utils import logger

if TYPE_CHECKING:
    from src.pipeline.overlay_pipeline import OverlayHandlingResult

log = logger.create_logger("Overlays")


# ====================================================================
# Overlay Message Helpers
# ====================================================================


def get_overlay_message(overlay_type: str | None) -> str:
    """Get appropriate message based on overlay type."""
    messages = {
        "cookie-consent": "Cookie consent detected",
        "sign-in": "Sign-in prompt detected",
        "newsletter": "Newsletter popup detected",
        "paywall": "Paywall detected",
        "age-verification": "Age verification detected",
    }
    return messages.get(overlay_type or "", "Overlay detected")


# ====================================================================
# Detection & Validation
# ====================================================================


async def detect_overlay(
    session: browser_session.BrowserSession,
    iteration: int,
) -> consent.CookieConsentDetection:
    """Run AI overlay detection on the current page state.

    Uses vision-only detection — the LLM analyses the screenshot
    to identify cookie consent dialogs and their dismiss buttons.

    Takes a viewport-only screenshot for detection (overlays are
    always visible in the viewport) to reduce image size and
    speed up LLM inference.
    """
    log.start_timer(f"overlay-detect-{iteration + 1}")

    # Use a viewport-only screenshot for faster detection.
    # Overlays always cover the viewport, so full-page is unnecessary.
    viewport_screenshot = await session.take_screenshot(full_page=False)
    log.debug(
        "Running overlay detection",
        {
            "iteration": iteration + 1,
            "screenshotBytes": len(viewport_screenshot),
        },
    )

    log.info("Sending screenshot to consent detection model...")
    detection = await consent_detection_mod.detect_cookie_consent(viewport_screenshot)
    log.end_timer(
        f"overlay-detect-{iteration + 1}",
        "Overlay detection complete",
    )
    return detection


async def validate_overlay_in_dom(
    page: async_api.Page,
    detection: consent.CookieConsentDetection,
) -> async_api.Frame | None:
    """Check that the LLM-detected element actually exists in the DOM.

    Guards against false positives where the LLM hallucinates
    overlays from ads or page furniture.

    Returns the frame where the element was found, or ``None``
    if it wasn't found anywhere.
    """
    found_frame = await click.validate_element_exists(page, detection.selector, detection.button_text)
    if not found_frame:
        log.warn(
            "Overlay detected by LLM but element not found in DOM — treating as false positive",
            {
                "selector": detection.selector,
                "buttonText": detection.button_text,
            },
        )
    return found_frame


# ====================================================================
# Click & Capture
# ====================================================================


async def click_and_capture(
    session: browser_session.BrowserSession,
    page: async_api.Page,
    detection: consent.CookieConsentDetection,
    overlay_number: int,
    progress_base: int,
    *,
    found_in_frame: async_api.Frame | None = None,
) -> AsyncGenerator[str, None]:
    """Click the overlay dismiss button and capture resulting state.

    Yields SSE events for progress, the post-click screenshot,
    and the consent detection event.  The first value yielded
    is always a ``bool`` indicating whether the click succeeded,
    followed by SSE event strings on success.
    """
    log.start_timer(f"overlay-click-{overlay_number}")

    clicked = await click.try_click_consent_button(
        page,
        detection.selector,
        detection.button_text,
        found_in_frame=found_in_frame,
    )
    log.end_timer(
        f"overlay-click-{overlay_number}",
        "Click succeeded" if clicked else "Click failed",
    )

    if not clicked:
        return

    yield sse_helpers.format_progress_event(
        f"overlay-{overlay_number}-wait",
        "Waiting for page to update...",
        progress_base + 2,
    )

    # Wait for DOM to settle (up to 800ms).
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(0.8):
            await session.wait_for_load_state("domcontentloaded")

    yield sse_helpers.format_progress_event(
        f"overlay-{overlay_number}-capture",
        "Capturing page state...",
        progress_base + 3,
    )
    await session.capture_current_cookies()

    event_str, _, _ = await sse_helpers.take_screenshot_event(
        session,
        extra={"overlayDismissed": detection.overlay_type},
    )
    yield event_str

    log.success(f"Overlay {overlay_number} ({detection.overlay_type}) dismissed successfully")

    yield sse_helpers.format_sse_event(
        "consent",
        {
            "detected": True,
            "clicked": True,
            "details": {
                "found": detection.found,
                "overlayType": detection.overlay_type,
                "selector": detection.selector,
                "buttonText": detection.button_text,
                "confidence": detection.confidence,
                "reason": detection.reason,
            },
            "overlayNumber": overlay_number,
        },
    )


# ====================================================================
# Consent Dialog Expansion
# ====================================================================

# Button labels that typically expand the consent dialog to show
# partner lists, detailed categories, vendor info, etc.
_EXPAND_LABELS: list[str] = [
    "More options",
    "More Options",
    "Manage options",
    "Manage Options",
    "Manage preferences",
    "Manage Preferences",
    "Cookie settings",
    "Cookie Settings",
    "Show partners",
    "View partners",
    "Show vendors",
    "View vendors",
    "Partner list",
    "Vendor list",
    "Customise",
    "Customize",
    "Purposes",
    "Legitimate interest",
]


async def expand_consent_dialog(
    page: async_api.Page,
    session: browser_session.BrowserSession,
) -> tuple[str, bytes]:
    """Try to expand a consent dialog before dismissing it.

    Clicks "More Options" / "Manage Preferences" style buttons
    to reveal hidden partner lists, detailed categories, and
    vendor information that is dynamically added to the DOM.

    After expansion (or if no expandable button is found),
    captures the consent DOM text and an updated screenshot.

    Args:
        page: Playwright page with the visible consent dialog.
        session: Browser session for taking screenshots.

    Returns:
        A tuple of (consent_text, screenshot) captured from
        the expanded (or original) dialog state.
    """
    expanded = False

    # Search in main frame and consent iframes
    frames: list[async_api.Frame] = [page.main_frame]
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        frame_url = frame.url.lower()
        if any(kw in frame_url for kw in constants.CONSENT_HOST_KEYWORDS):
            frames.append(frame)

    for label in _EXPAND_LABELS:
        if expanded:
            break
        for frame in frames:
            try:
                # Try button role first (most specific)
                btn = frame.get_by_role("button", name=label)
                if await btn.count() > 0:
                    await btn.first.click(timeout=3000)
                    log.info(
                        "Expanded consent dialog via button",
                        {"label": label},
                    )
                    expanded = True
                    break
            except Exception:
                pass
            try:
                # Fall back to any clickable element with
                # matching text (links, divs, etc.)
                el = frame.get_by_text(label, exact=True)
                if await el.count() > 0:
                    await el.first.click(timeout=3000)
                    log.info(
                        "Expanded consent dialog via text",
                        {"label": label},
                    )
                    expanded = True
                    break
            except Exception:
                pass

    if expanded:
        # Wait for the DOM to settle after the expand click
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(1.5):
                await page.wait_for_load_state("domcontentloaded")
        # Extra short wait for dynamic content to render
        await asyncio.sleep(0.5)
    else:
        log.debug("No expand button found on consent dialog")

    # Capture the consent text from the (possibly expanded) DOM
    consent_text = await consent_extraction_agent._extract_consent_text(page)
    screenshot = await session.take_screenshot(full_page=False)

    # Navigate back to the main consent view so the original
    # Accept button is still clickable.  Try common "back"
    # patterns used by CMP dialogs.
    if expanded:
        navigated_back = False
        back_labels = [
            "Back",
            "Back to main",
            "Go back",
            "← Back",
            "Save and exit",
        ]
        for label in back_labels:
            if navigated_back:
                break
            for frame in frames:
                try:
                    btn = frame.get_by_role("button", name=label)
                    if await btn.count() > 0:
                        await btn.first.click(timeout=3000)
                        log.info(
                            "Navigated back to main consent view",
                            {"label": label},
                        )
                        navigated_back = True
                        break
                except Exception:
                    pass
        if navigated_back:
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(1.0):
                    await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(0.3)

    log.info(
        "Pre-click consent capture complete",
        {
            "expanded": expanded,
            "textLength": len(consent_text),
        },
    )

    return consent_text, screenshot


# ====================================================================
# Consent Extraction
# ====================================================================


async def extract_and_classify_consent(
    page: async_api.Page,
    pre_click_screenshot: bytes,
    result: OverlayHandlingResult,
    pre_click_consent_text: str | None = None,
) -> AsyncGenerator[str, None]:
    """Extract consent details and classify partner risk levels.

    Only called for the first cookie-consent overlay after a
    successful click.  Uses the pre-click screenshot so the
    consent dialog is still visible for the extraction agent.

    Args:
        page: Playwright page (for fallback DOM extraction).
        pre_click_screenshot: Screenshot with dialog visible.
        result: Mutable overlay result to populate.
        pre_click_consent_text: DOM text captured while the
            consent dialog was still visible (and possibly
            expanded).  If provided, the extraction agent
            uses this instead of re-extracting from the
            (now-dismissed) page.
    """
    log.start_timer("consent-extraction")
    yield sse_helpers.format_progress_event(
        "consent-extract",
        "Extracting consent information...",
        71,
    )
    result.consent_details = await extraction.extract_consent_details(
        page,
        pre_click_screenshot,
        pre_captured_text=pre_click_consent_text,
    )
    log.end_timer("consent-extraction", "Consent details extracted")
    log.info(
        "Consent details",
        {
            "categories": len(result.consent_details.categories),
            "partners": len(result.consent_details.partners),
            "purposes": len(result.consent_details.purposes),
        },
    )

    # Enrich partners with risk classification
    if result.consent_details.partners:
        log.start_timer("partner-classification")
        yield sse_helpers.format_progress_event(
            "partner-classify",
            "Classifying partners...",
            72,
        )

        risk_summary = partner_classification.get_partner_risk_summary(result.consent_details.partners)
        log.info(
            "Partner risk summary",
            {
                "critical": risk_summary.critical_count,
                "high": risk_summary.high_count,
                "totalRisk": risk_summary.total_risk_score,
            },
        )

        for partner in result.consent_details.partners:
            classification = partner_classification.classify_partner_by_pattern_sync(partner)
            if classification:
                partner.risk_level = classification.risk_level
                partner.risk_category = classification.category
                partner.risk_score = classification.risk_score
                partner.concerns = classification.concerns
            else:
                partner.risk_level = "unknown"
                partner.risk_score = 3

        log.end_timer(
            "partner-classification",
            "Partner classification complete",
        )

    yield sse_helpers.format_sse_event(
        "consentDetails",
        sse_helpers.serialize_consent_details(result.consent_details),
    )


async def collect_extraction_events(
    page: async_api.Page,
    pre_click_screenshot: bytes,
    result: OverlayHandlingResult,
    pre_click_consent_text: str | None = None,
) -> list[str]:
    """Run consent extraction, returning events for deferred yielding.

    Used when extraction runs concurrently with the next
    detection call to avoid blocking the overlay loop.
    """
    events: list[str] = []
    async for event in extract_and_classify_consent(
        page,
        pre_click_screenshot,
        result,
        pre_click_consent_text=pre_click_consent_text,
    ):
        events.append(event)
    return events


# ====================================================================
# SSE Event Builders
# ====================================================================


def build_no_overlay_events(
    overlay_count: int,
    reason: str | None,
) -> list[str]:
    """Build SSE events for the 'no overlay found' case."""
    if overlay_count == 0:
        log.info("No overlay detected", {"reason": reason})
        return [
            sse_helpers.format_progress_event("consent-none", "No consent dialog detected...", 70),
            sse_helpers.format_sse_event(
                "consent",
                {
                    "detected": False,
                    "clicked": False,
                    "details": None,
                    "reason": reason,
                },
            ),
        ]
    dismissed_label = "overlay" if overlay_count == 1 else "overlays"
    log.success(f"Dismissed {overlay_count} {dismissed_label}, no more found")
    dismissed_text = "Dismissed 1 overlay..." if overlay_count == 1 else f"Dismissed {overlay_count} overlays..."
    return [
        sse_helpers.format_progress_event(
            "overlays-done",
            dismissed_text,
            70,
        )
    ]


def build_click_failure(
    detection: consent.CookieConsentDetection,
    overlay_number: int,
    error_detail: str | None = None,
) -> tuple[str, str]:
    """Build click failure SSE event and message."""
    if error_detail:
        msg = f"Failed to dismiss {detection.overlay_type or 'overlay'}: {error_detail}"
    else:
        msg = f"Failed to dismiss {detection.overlay_type or 'overlay'} (button: '{detection.button_text or detection.selector}')"

    event = sse_helpers.format_sse_event(
        "consent",
        {
            "detected": True,
            "clicked": False,
            "details": {
                "found": detection.found,
                "overlayType": detection.overlay_type,
                "selector": detection.selector,
                "buttonText": detection.button_text,
                "confidence": detection.confidence,
                "reason": detection.reason,
            },
            "error": msg,
            "overlayNumber": overlay_number,
        },
    )
    return event, msg


# ====================================================================
# Detection Key Helpers
# ====================================================================


def infer_accessor_type(
    detection: consent.CookieConsentDetection,
) -> overlay_cache.AccessorType:
    """Infer how the overlay element was located.

    Uses the detection fields to determine whether the
    element was found via CSS selector, button role, or
    text search.
    """
    if detection.selector:
        return "css-selector"
    if detection.button_text:
        return "button-role"
    return "text-search"


def detection_signature(
    detection: consent.CookieConsentDetection,
) -> str:
    """Build a hashable key for a detection to track repeats."""
    return f"{detection.selector or ''}|{detection.button_text or ''}"
