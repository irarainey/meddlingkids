"""
Helper functions for the streaming analysis handler.
Extracts reusable logic for overlay handling, screenshot capture, etc.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, AsyncGenerator

from playwright.async_api import Page

from src.services.browser_session import BrowserSession
from src.services.consent_click import try_click_consent_button
from src.services.consent_detection import detect_cookie_consent
from src.services.consent_extraction import extract_consent_details
from src.services.partner_classification import (
    classify_partner_by_pattern_sync,
    get_partner_risk_summary,
)
from src.types.tracking import ConsentDetails, CookieConsentDetection, StorageItem
from src.utils.logger import create_logger

log = create_logger("Overlays")


def _snake_to_camel(name: str) -> str:
    """Convert snake_case to camelCase."""
    parts = name.split("_")
    return parts[0] + "".join(w.capitalize() for w in parts[1:])


def to_camel_case_dict(obj: object) -> dict[str, Any]:
    """Convert a dataclass instance to a dict with camelCase keys."""
    return {_snake_to_camel(k): v for k, v in obj.__dict__.items()}


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


class OverlayHandlingResult:
    """Result of handling overlays."""

    def __init__(self) -> None:
        self.overlay_count: int = 0
        self.dismissed_overlays: list[CookieConsentDetection] = []
        self.consent_details: ConsentDetails | None = None
        self.final_screenshot: bytes = b""
        self.final_storage: dict[str, list[StorageItem]] = {
            "localStorage": [],
            "sessionStorage": [],
        }
        self.events: list[str] = []


async def handle_overlays(
    session: BrowserSession,
    page: Page,
    initial_screenshot: bytes,
) -> OverlayHandlingResult:
    """
    Handle multiple overlays (cookie consent, sign-in walls, etc.) in sequence.
    Captures consent details from the first cookie consent dialog.

    Returns an OverlayHandlingResult containing any SSE events to emit.
    """
    result = OverlayHandlingResult()
    screenshot = initial_screenshot
    storage = await session.capture_storage()
    result.final_storage = storage

    log.info("Starting overlay detection loop", {"maxOverlays": MAX_OVERLAYS})

    overlay_count = 0
    while overlay_count < MAX_OVERLAYS:
        log.start_timer(f"overlay-detect-{overlay_count + 1}")
        html = await session.get_page_content()
        consent_detection = await detect_cookie_consent(screenshot, html)
        log.end_timer(f"overlay-detect-{overlay_count + 1}", "Overlay detection complete")

        if not consent_detection.found or not consent_detection.selector:
            if overlay_count == 0:
                log.info("No overlay detected")
                result.events.append(format_progress_event("consent-none", "No overlay detected", 70))
                result.events.append(format_sse_event("consent", {
                    "detected": False,
                    "clicked": False,
                    "details": None,
                    "reason": consent_detection.reason,
                }))
            else:
                log.success(f"Dismissed {overlay_count} overlay(s), no more found")
                result.events.append(format_progress_event("overlays-done", f"Dismissed {overlay_count} overlay(s)", 70))
            break

        overlay_count += 1
        progress_base = 45 + (overlay_count * 5)

        log.info(f"Overlay {overlay_count} found", {
            "type": consent_detection.overlay_type,
            "selector": consent_detection.selector,
            "buttonText": consent_detection.button_text,
            "confidence": consent_detection.confidence,
        })
        result.events.append(format_progress_event(
            f"overlay-{overlay_count}-found",
            _get_overlay_message(consent_detection.overlay_type),
            progress_base,
        ))
        result.dismissed_overlays.append(consent_detection)

        # Extract consent details BEFORE accepting (first cookie consent only)
        if consent_detection.overlay_type == "cookie-consent" and not result.consent_details:
            log.start_timer("consent-extraction")
            result.events.append(format_progress_event("consent-extract", "Extracting consent details...", progress_base + 1))
            result.consent_details = await extract_consent_details(page, screenshot)
            log.end_timer("consent-extraction", "Consent details extracted")
            log.info("Consent details", {
                "categories": len(result.consent_details.categories),
                "partners": len(result.consent_details.partners),
                "purposes": len(result.consent_details.purposes),
            })

            # Enrich partners with risk classification
            if result.consent_details.partners:
                log.start_timer("partner-classification")
                result.events.append(format_progress_event("partner-classify", "Analyzing partner risk levels...", progress_base + 2))

                risk_summary = get_partner_risk_summary(result.consent_details.partners)
                log.info("Partner risk summary", {
                    "critical": risk_summary["criticalCount"],
                    "high": risk_summary["highCount"],
                    "totalRisk": risk_summary["totalRiskScore"],
                })

                for partner in result.consent_details.partners:
                    classification = classify_partner_by_pattern_sync(partner)
                    if classification:
                        partner.risk_level = classification.risk_level
                        partner.risk_category = classification.category
                        partner.risk_score = classification.risk_score
                        partner.concerns = classification.concerns
                    else:
                        partner.risk_level = "unknown"
                        partner.risk_score = 3

                log.end_timer("partner-classification", "Partner classification complete")

            result.events.append(format_sse_event("consentDetails", {
                "categories": [
                    {"name": c.name, "description": c.description, "required": c.required}
                    for c in result.consent_details.categories
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
                    for p in result.consent_details.partners
                ],
                "purposes": result.consent_details.purposes,
                "hasManageOptions": result.consent_details.has_manage_options,
            }))

        # Try to click the dismiss/accept button
        try:
            log.start_timer(f"overlay-click-{overlay_count}")
            result.events.append(format_progress_event(f"overlay-{overlay_count}-click", "Dismissing overlay...", progress_base + 3))

            clicked = await try_click_consent_button(page, consent_detection.selector, consent_detection.button_text)
            log.end_timer(f"overlay-click-{overlay_count}", "Click succeeded" if clicked else "Click failed")

            if clicked:
                result.events.append(format_progress_event(f"overlay-{overlay_count}-wait", "Waiting for page to update...", progress_base + 4))

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

                result.events.append(format_progress_event(f"overlay-{overlay_count}-capture", "Capturing page state...", progress_base + 5))
                await session.capture_current_cookies()
                storage = await session.capture_storage()
                screenshot = await session.take_screenshot(full_page=False)
                b64 = base64.b64encode(screenshot).decode("utf-8")

                log.success(f"Overlay {overlay_count} ({consent_detection.overlay_type}) dismissed successfully")

                result.events.append(format_sse_event("screenshot", {
                    "screenshot": f"data:image/png;base64,{b64}",
                    "cookies": [to_camel_case_dict(c) for c in session.get_tracked_cookies()],
                    "scripts": [to_camel_case_dict(s) for s in session.get_tracked_scripts()],
                    "networkRequests": [to_camel_case_dict(r) for r in session.get_tracked_network_requests()],
                    "localStorage": [to_camel_case_dict(i) for i in storage["localStorage"]],
                    "sessionStorage": [to_camel_case_dict(i) for i in storage["sessionStorage"]],
                    "overlayDismissed": consent_detection.overlay_type,
                }))

                result.events.append(format_sse_event("consent", {
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
                }))
            else:
                log.warn(f"Failed to click overlay {overlay_count}, stopping overlay detection")
                result.events.append(format_sse_event("consent", {
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
                    "error": "Failed to click dismiss button",
                    "overlayNumber": overlay_count,
                }))
                break
        except Exception as click_error:
            log.error(f"Failed to click overlay {overlay_count}", {"error": str(click_error)})
            result.events.append(format_sse_event("consent", {
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
                "error": "Failed to click dismiss button",
                "overlayNumber": overlay_count,
            }))
            break

    if overlay_count >= MAX_OVERLAYS:
        log.warn("Reached maximum overlay limit, stopping detection")
        result.events.append(format_progress_event("overlays-limit", "Maximum overlay limit reached", 70))

    result.overlay_count = overlay_count
    result.final_screenshot = screenshot
    result.final_storage = storage

    return result
