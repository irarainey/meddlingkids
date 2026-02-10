"""
Helper functions for the streaming analysis handler.
Extracts reusable logic for overlay handling, screenshot capture, etc.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator

import pydantic
from playwright import async_api

from src.services import (
    browser_session,
    consent_click,
    consent_extraction,
    partner_classification,
)
from src.services import consent_detection as consent_detection_mod
from src.types import analysis, consent, tracking_data
from src.utils import logger

log = logger.create_logger("Overlays")


def _snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase."""
    parts = name.split("_")
    return parts[0] + "".join(w.capitalize() for w in parts[1:])


def to_camel_case_dict(obj: pydantic.BaseModel) -> dict[str, Any]:
    """Convert a Pydantic model instance to a dict with camelCase keys."""
    return {_snake_to_camel(k): v for k, v in obj.model_dump().items()}


def serialize_consent_details(details: consent.ConsentDetails) -> dict[str, Any]:
    """Serialize ConsentDetails to a camelCase dict for SSE transport."""
    return {
        "categories": [
            {"name": c.name, "description": c.description, "required": c.required}
            for c in details.categories
        ],
        "partners": [
            {
                "name": p.name,
                "purpose": p.purpose,
                "dataCollected": p.data_collected,
                "riskLevel": p.risk_level,
                "riskCategory": p.risk_category,
                "riskScore": p.risk_score,
                "concerns": p.concerns,
            }
            for p in details.partners
        ],
        "purposes": details.purposes,
        "hasManageOptions": details.has_manage_options,
    }


def serialize_score_breakdown(sb: analysis.ScoreBreakdown) -> dict[str, Any]:
    """Serialize ScoreBreakdown to a camelCase dict for SSE transport."""
    return {
        "totalScore": sb.total_score,
        "categories": {
            name: {"points": cat.points, "maxPoints": cat.max_points, "issues": cat.issues}
            for name, cat in sb.categories.items()
        },
        "factors": sb.factors,
        "summary": sb.summary,
    }


# ============================================================================
# SSE Helper Functions
# ============================================================================

def format_sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent Event string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def format_progress_event(step: str, message: str, progress: int) -> str:
    """Format a progress SSE event."""
    return format_sse_event("progress", {"step": step, "message": message, "progress": progress})


# ============================================================================
# Overlay Handling
# ============================================================================

MAX_OVERLAYS = 5


def _get_overlay_message(overlay_type: str | None) -> str:
    """Get appropriate message based on overlay type."""
    messages = {
        "cookie-consent": "Cookie consent detected",
        "sign-in": "Sign-in prompt detected",
        "newsletter": "Newsletter popup detected",
        "paywall": "Paywall detected",
        "age-verification": "Age verification detected",
    }
    return messages.get(overlay_type or "", "Overlay detected")


class OverlayHandlingResult(pydantic.BaseModel):
    """Mutable state populated by the handle_overlays async generator."""

    overlay_count: int = 0
    dismissed_overlays: list[consent.CookieConsentDetection] = pydantic.Field(
        default_factory=list
    )
    consent_details: consent.ConsentDetails | None = None
    failed: bool = False
    failure_message: str = ""
    final_screenshot: bytes = b""
    final_storage: dict[str, list[tracking_data.StorageItem]] = pydantic.Field(
        default_factory=lambda: {
            "local_storage": [],
            "session_storage": [],
        }
    )


async def handle_overlays(
    session: browser_session.BrowserSession,
    page: async_api.Page,
    initial_screenshot: bytes,
    result: OverlayHandlingResult,
) -> AsyncGenerator[str, None]:
    """
    Handle multiple overlays (cookie consent, sign-in walls, etc.) in sequence.
    Captures consent details from the first cookie consent dialog.

    Yields SSE event strings immediately as they are generated so the client
    receives screenshots and progress updates without delay.

    Mutates *result* in-place with final state (overlay count, consent
    details, storage, etc.).
    """
    screenshot = initial_screenshot
    storage = await session.capture_storage()
    result.final_storage = storage

    log.info("Starting overlay detection loop", {"maxOverlays": MAX_OVERLAYS})

    overlay_count = 0
    while overlay_count < MAX_OVERLAYS:
        log.start_timer(f"overlay-detect-{overlay_count + 1}")
        html = await session.get_page_content()
        consent_detection = await consent_detection_mod.detect_cookie_consent(screenshot, html)
        log.end_timer(f"overlay-detect-{overlay_count + 1}", "Overlay detection complete")

        if not consent_detection.found or not consent_detection.selector:
            if overlay_count == 0:
                log.info("No overlay detected")
                yield format_progress_event("consent-none", "No overlay detected", 70)
                yield format_sse_event("consent", {
                    "detected": False,
                    "clicked": False,
                    "details": None,
                    "reason": consent_detection.reason,
                })
            else:
                log.success(f"Dismissed {overlay_count} overlay(s), no more found")
                yield format_progress_event("overlays-done", f"Dismissed {overlay_count} overlay(s)", 70)
            break

        overlay_count += 1
        progress_base = 45 + (overlay_count * 5)

        log.info(f"Overlay {overlay_count} found", {
            "type": consent_detection.overlay_type,
            "selector": consent_detection.selector,
            "buttonText": consent_detection.button_text,
            "confidence": consent_detection.confidence,
        })
        yield format_progress_event(
            f"overlay-{overlay_count}-found",
            _get_overlay_message(consent_detection.overlay_type),
            progress_base,
        )
        result.dismissed_overlays.append(consent_detection)

        # Whether this is the first cookie-consent overlay (used for
        # post-click extraction).  We remember the pre-click screenshot
        # so extraction can run AFTER the click succeeds.
        is_first_cookie_consent = (
            consent_detection.overlay_type == "cookie-consent"
            and not result.consent_details
        )
        pre_click_screenshot = screenshot if is_first_cookie_consent else None

        # -----------------------------------------------------------
        # Click the dismiss/accept button FIRST — before extraction.
        # Extraction can take a very long time (LLM vision call) and
        # some consent banners auto-dismiss after a timeout.  Clicking
        # immediately keeps the page in a usable state.
        # -----------------------------------------------------------
        try:
            log.start_timer(f"overlay-click-{overlay_count}")
            yield format_progress_event(f"overlay-{overlay_count}-click", "Dismissing overlay...", progress_base + 1)

            clicked = await consent_click.try_click_consent_button(page, consent_detection.selector, consent_detection.button_text)
            log.end_timer(f"overlay-click-{overlay_count}", "Click succeeded" if clicked else "Click failed")

            if clicked:
                yield format_progress_event(f"overlay-{overlay_count}-wait", "Waiting for page to update...", progress_base + 2)

                # Wait for DOM to settle (race timeout vs load state)
                done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(session.wait_for_timeout(800)),
                        asyncio.create_task(session.wait_for_load_state("domcontentloaded")),
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

                yield format_progress_event(f"overlay-{overlay_count}-capture", "Capturing page state...", progress_base + 3)
                await session.capture_current_cookies()
                storage = await session.capture_storage()
                screenshot = await session.take_screenshot(full_page=False)
                optimized = browser_session.BrowserSession.optimize_screenshot_bytes(screenshot)

                log.success(f"Overlay {overlay_count} ({consent_detection.overlay_type}) dismissed successfully")

                yield format_sse_event("screenshot", {
                    "screenshot": optimized,
                    "cookies": [to_camel_case_dict(c) for c in session.get_tracked_cookies()],
                    "scripts": [to_camel_case_dict(s) for s in session.get_tracked_scripts()],
                    "networkRequests": [to_camel_case_dict(r) for r in session.get_tracked_network_requests()],
                    "localStorage": [to_camel_case_dict(i) for i in storage["local_storage"]],
                    "sessionStorage": [to_camel_case_dict(i) for i in storage["session_storage"]],
                    "overlayDismissed": consent_detection.overlay_type,
                })

                yield format_sse_event("consent", {
                    "detected": True,
                    "clicked": True,
                    "details": {
                        "found": consent_detection.found,
                        "overlayType": consent_detection.overlay_type,
                        "selector": consent_detection.selector,
                        "buttonText": consent_detection.button_text,
                        "confidence": consent_detection.confidence,
                        "reason": consent_detection.reason,
                    },
                    "overlayNumber": overlay_count,
                })

                # -------------------------------------------------------
                # Extract consent details AFTER the click.  Uses the
                # pre-click screenshot so we still see the consent dialog.
                # -------------------------------------------------------
                if is_first_cookie_consent and pre_click_screenshot is not None:
                    log.start_timer("consent-extraction")
                    yield format_progress_event("consent-extract", "Extracting consent details...", progress_base + 4)
                    result.consent_details = await consent_extraction.extract_consent_details(page, pre_click_screenshot)
                    log.end_timer("consent-extraction", "Consent details extracted")
                    log.info("Consent details", {
                        "categories": len(result.consent_details.categories),
                        "partners": len(result.consent_details.partners),
                        "purposes": len(result.consent_details.purposes),
                    })

                    # Enrich partners with risk classification
                    if result.consent_details.partners:
                        log.start_timer("partner-classification")
                        yield format_progress_event("partner-classify", "Analyzing partner risk levels...", progress_base + 5)

                        risk_summary = partner_classification.get_partner_risk_summary(
                            result.consent_details.partners
                        )
                        log.info("Partner risk summary", {
                            "critical": risk_summary.critical_count,
                            "high": risk_summary.high_count,
                            "totalRisk": risk_summary.total_risk_score,
                        })

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

                        log.end_timer("partner-classification", "Partner classification complete")

                    yield format_sse_event("consentDetails",
                        serialize_consent_details(result.consent_details))
            else:
                msg = (
                    f"Failed to dismiss {consent_detection.overlay_type or 'overlay'} "
                    f"(button: '{consent_detection.button_text or consent_detection.selector}')"
                )
                log.error(f"Failed to click overlay {overlay_count}, aborting analysis")
                result.failed = True
                result.failure_message = msg
                yield format_sse_event("consent", {
                    "detected": True,
                    "clicked": False,
                    "details": {
                        "found": consent_detection.found,
                        "overlayType": consent_detection.overlay_type,
                        "selector": consent_detection.selector,
                        "buttonText": consent_detection.button_text,
                        "confidence": consent_detection.confidence,
                        "reason": consent_detection.reason,
                    },
                    "error": msg,
                    "overlayNumber": overlay_count,
                })
                break
        except Exception as click_error:
            msg = (
                f"Failed to dismiss {consent_detection.overlay_type or 'overlay'}: "
                f"{click_error}"
            )
            log.error(f"Failed to click overlay {overlay_count}", {"error": str(click_error)})
            result.failed = True
            result.failure_message = msg
            yield format_sse_event("consent", {
                "detected": True,
                "clicked": False,
                "details": {
                    "found": consent_detection.found,
                    "overlayType": consent_detection.overlay_type,
                    "selector": consent_detection.selector,
                    "buttonText": consent_detection.button_text,
                    "confidence": consent_detection.confidence,
                    "reason": consent_detection.reason,
                },
                "error": msg,
                "overlayNumber": overlay_count,
            })
            break

    if overlay_count >= MAX_OVERLAYS:
        log.warn("Reached maximum overlay limit, stopping detection")
        yield format_progress_event("overlays-limit", "Maximum overlay limit reached", 70)

    result.overlay_count = overlay_count
    result.final_screenshot = screenshot
    result.final_storage = storage
