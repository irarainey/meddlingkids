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
from src.consent import click, extraction, partner_classification
from src.consent import detection as consent_detection_mod
from src.models import consent
from src.pipeline import sse_helpers
from src.utils import image, logger

# Bounding-box type alias used throughout the overlay pipeline.
ConsentBounds = tuple[int, int, int, int] | None

if TYPE_CHECKING:
    from src.pipeline.overlay_pipeline import OverlayHandlingResult

log = logger.create_logger("OverlaySteps")


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
    to identify page overlays and their dismiss buttons.

    Takes a viewport-only screenshot for detection (overlays are
    always visible in the viewport) to reduce image size and
    speed up LLM inference.

    When the consent dialog can be located in the DOM, the
    screenshot is cropped to just the dialog area before being
    sent to the LLM.  This avoids content-filter rejections
    caused by background page imagery and reduces token usage.
    """
    log.start_timer(f"overlay-detect-{iteration + 1}")

    # Use a viewport-only screenshot for faster detection.
    # Overlays always cover the viewport, so full-page is unnecessary.
    try:
        viewport_screenshot = await session.take_screenshot(
            full_page=False,
            timeout=30_000,
        )
    except Exception as exc:
        log.warn(
            "Screenshot failed during overlay detection — skipping",
            {"iteration": iteration + 1, "error": str(exc)},
        )
        log.end_timer(
            f"overlay-detect-{iteration + 1}",
            "Screenshot failed",
        )
        return consent.CookieConsentDetection.not_found(
            reason=f"Screenshot failed: {exc}",
        )

    # ── Speculative crop ────────────────────────────────
    # Try to locate the consent dialog via known CSS selectors
    # and crop the screenshot to just that region.  This
    # prevents background page content from triggering
    # Azure content filters during LLM vision analysis.
    detection_screenshot = viewport_screenshot
    page = session.get_page()
    if page is not None:
        try:
            raw = await page.evaluate(
                consent_extraction_agent._GET_CONSENT_BOUNDS_JS,
            )
            if raw and isinstance(raw, dict):
                crop_box: tuple[int, int, int, int] = (
                    int(raw["left"]),
                    int(raw["top"]),
                    int(raw["right"]),
                    int(raw["bottom"]),
                )
                cropped = image.crop_jpeg(viewport_screenshot, crop_box)
                if cropped is not viewport_screenshot:
                    detection_screenshot = cropped
                    log.info(
                        "Cropped detection screenshot to consent dialog",
                        {"bounds": crop_box},
                    )
        except Exception as exc:
            log.debug(
                "Speculative consent bounds detection failed — using full screenshot",
                {"error": str(exc)},
            )

    log.debug(
        "Running overlay detection",
        {
            "iteration": iteration + 1,
            "screenshotBytes": len(detection_screenshot),
            "cropped": detection_screenshot is not viewport_screenshot,
        },
    )

    log.info("Sending screenshot to overlay detection model...")
    try:
        detection = await consent_detection_mod.detect_cookie_consent(detection_screenshot)
    except TimeoutError:
        log.warn(
            "Overlay detection timed out",
            {"iteration": iteration + 1},
        )
        log.end_timer(
            f"overlay-detect-{iteration + 1}",
            "Overlay detection timed out",
        )
        return consent.CookieConsentDetection.failed(
            reason="Overlay detection timed out",
        )
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


async def try_overlay_click(
    page: async_api.Page,
    detection: consent.CookieConsentDetection,
    overlay_number: int,
    *,
    found_in_frame: async_api.Frame | None = None,
) -> click.ClickResult:
    """Attempt to click the overlay dismiss button.

    Returns a :class:`~click.ClickResult` with the Playwright
    strategy and frame type that succeeded, or a failed result.
    """
    log.start_timer(f"overlay-click-{overlay_number}")

    result = await click.try_click_consent_button(
        page,
        detection.selector,
        detection.button_text,
        found_in_frame=found_in_frame,
    )
    log.end_timer(
        f"overlay-click-{overlay_number}",
        "Click succeeded" if result.success else "Click failed",
    )
    return result


async def capture_after_click(
    session: browser_session.BrowserSession,
    page: async_api.Page,
    detection: consent.CookieConsentDetection,
    overlay_number: int,
    progress_base: int,
) -> AsyncGenerator[str]:
    """Capture page state after a successful overlay click.

    Yields SSE events for progress, the post-click screenshot,
    and the consent detection event.  Must only be called after
    :func:`try_overlay_click` returns a successful result.
    """
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


# ====================================================================
# Pre-Dismiss Content Capture
# ====================================================================


async def capture_consent_content(
    page: async_api.Page,
    session: browser_session.BrowserSession,
) -> tuple[str, bytes, ConsentBounds]:
    """Capture consent dialog content before dismissing it.

    Extracts DOM text from the consent dialog (main page and
    consent-manager iframes), takes a viewport screenshot
    while the overlay is still visible, and determines the
    bounding box of the consent dialog element so the
    screenshot can be cropped before sending to the LLM.

    This is intentionally a *read-only* step — it does not
    click any buttons or expand the dialog.  The goal is to
    gather as much information as possible from the overlay
    in its current state.

    Args:
        page: Playwright page with the visible consent dialog.
        session: Browser session for taking screenshots.

    Returns:
        A ``(consent_text, screenshot, consent_bounds)`` tuple
        where *consent_bounds* is ``(left, top, right, bottom)``
        or ``None`` when the dialog element could not be located.
    """
    consent_text = await consent_extraction_agent._extract_consent_text(page)
    try:
        screenshot = await session.take_screenshot(full_page=False)
    except Exception as exc:
        log.warn(
            "Screenshot failed during consent capture — using empty image",
            {"error": str(exc)},
        )
        screenshot = b""

    # Locate the consent dialog bounding box for screenshot cropping.
    consent_bounds: ConsentBounds = None
    try:
        raw = await page.evaluate(consent_extraction_agent._GET_CONSENT_BOUNDS_JS)
        if raw and isinstance(raw, dict):
            consent_bounds = (
                int(raw["left"]),
                int(raw["top"]),
                int(raw["right"]),
                int(raw["bottom"]),
            )
            log.info(
                "Consent dialog bounds detected",
                {"bounds": consent_bounds},
            )
    except Exception as exc:
        log.debug(
            "Consent bounds detection failed",
            {"error": str(exc)},
        )

    log.info(
        "Pre-dismiss consent capture complete",
        {"textLength": len(consent_text), "hasBounds": consent_bounds is not None},
    )
    return consent_text, screenshot, consent_bounds


# ====================================================================
# Consent Extraction
# ====================================================================


async def extract_and_classify_consent(
    page: async_api.Page,
    pre_click_screenshot: bytes,
    result: OverlayHandlingResult,
    pre_click_consent_text: str | None = None,
    consent_platform: str | None = None,
    consent_bounds: ConsentBounds = None,
) -> AsyncGenerator[str]:
    """Extract consent details and classify partner risk levels.

    Only called for the first cookie-consent overlay after a
    successful click.  Uses the pre-click screenshot so the
    consent dialog is still visible for the extraction agent.

    Args:
        page: Playwright page (for fallback DOM extraction).
        pre_click_screenshot: Screenshot with dialog visible.
        result: Mutable overlay result to populate.
        pre_click_consent_text: DOM text captured while the
            consent dialog was still visible.  If provided,
            the extraction agent uses this instead of
            re-extracting from the (now-dismissed) page.
        consent_bounds: ``(left, top, right, bottom)`` pixel
            region of the consent dialog for screenshot cropping.
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
        consent_bounds=consent_bounds,
    )
    if consent_platform:
        result.consent_details.consent_platform = consent_platform
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
    consent_platform: str | None = None,
    consent_bounds: ConsentBounds = None,
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
        consent_platform=consent_platform,
        consent_bounds=consent_bounds,
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
            sse_helpers.format_progress_event("consent-none", "No overlay detected...", 70),
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
) -> str:
    """Build click failure log message.

    Returns:
        Human-readable failure description.
    """
    if error_detail:
        msg = f"Failed to dismiss {detection.overlay_type or 'overlay'}: {error_detail}"
    else:
        msg = f"Failed to dismiss {detection.overlay_type or 'overlay'} (button: '{detection.button_text or detection.selector}')"

    return msg


# ====================================================================
# Detection Key Helpers
# ====================================================================


def detection_signature(
    detection: consent.CookieConsentDetection,
) -> str:
    """Build a hashable key for a detection to track repeats."""
    return f"{detection.selector or ''}|{detection.button_text or ''}"
