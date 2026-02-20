"""
Server-Sent Events formatting and data serialization helpers.

Pure functions with no side-effects — safe to import from any module
in the routes package.
"""

from __future__ import annotations

import json
from typing import Any

import pydantic

from src.browser import session as browser_session
from src.models import analysis, consent, tracking_data
from src.utils import logger, serialization

log = logger.create_logger("SSE-Helpers")

# ====================================================================
# camelCase Serialization
# ====================================================================


def to_camel_case_dict(obj: pydantic.BaseModel) -> dict[str, Any]:
    """Convert a Pydantic model instance to a dict with camelCase keys."""

    return {serialization.snake_to_camel(k): v for k, v in obj.model_dump().items()}


def serialize_consent_details(
    details: consent.ConsentDetails,
) -> dict[str, Any]:
    """Serialize ConsentDetails to a camelCase dict for SSE transport."""
    data = details.model_dump(by_alias=True)
    # Exclude internal fields not needed by the client.
    data.pop("rawText", None)
    return data


def serialize_score_breakdown(
    sb: analysis.ScoreBreakdown,
) -> dict[str, Any]:
    """Serialize ScoreBreakdown to a camelCase dict for SSE transport."""
    return sb.model_dump(by_alias=True)


# ====================================================================
# SSE Formatting
# ====================================================================


def format_sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent Event string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def format_progress_event(step: str, message: str, progress: int) -> str:
    """Format a progress SSE event."""
    return format_sse_event(
        "progress",
        {"step": step, "message": message, "progress": progress},
    )


# ====================================================================
# Screenshot Event Builders
# ====================================================================


def build_screenshot_event(
    session: browser_session.BrowserSession,
    optimized_screenshot: str,
    storage: tracking_data.CapturedStorage,
    *,
    extra: dict[str, Any] | None = None,
) -> str:
    """Build and format a screenshot SSE event with tracking data.

    Consolidates the repeated pattern of capturing tracked data
    from the session and packaging it into a screenshot event.

    Args:
        session: Active browser session with tracked data.
        optimized_screenshot: Base64 JPEG data URL string.
        storage: Captured browser storage.
        extra: Optional additional fields to merge into the
            event payload.

    Returns:
        Formatted SSE event string.
    """
    payload: dict[str, Any] = {
        "screenshot": optimized_screenshot,
        "cookies": [to_camel_case_dict(c) for c in session.get_tracked_cookies()],
        "scripts": [to_camel_case_dict(s) for s in session.get_tracked_scripts()],
        "networkRequests": [to_camel_case_dict(r) for r in session.get_tracked_network_requests()],
        "localStorage": [to_camel_case_dict(i) for i in storage.local_storage],
        "sessionStorage": [to_camel_case_dict(i) for i in storage.session_storage],
    }
    if extra:
        payload.update(extra)
    return format_sse_event("screenshot", payload)


def format_screenshot_update_event(
    optimized_screenshot: str,
) -> str:
    """Format a screenshotUpdate SSE event.

    This lightweight event carries only the image data and
    tells the client to *replace* the most recent screenshot
    rather than appending a new one.  Used by the background
    screenshot refresher to keep the gallery up-to-date as
    ads and deferred content load in.
    """
    return format_sse_event(
        "screenshotUpdate",
        {"screenshot": optimized_screenshot},
    )


async def take_screenshot_event(
    session: browser_session.BrowserSession,
    storage: tracking_data.CapturedStorage | None = None,
    *,
    extra: dict[str, Any] | None = None,
) -> tuple[str, bytes, tracking_data.CapturedStorage]:
    """Take a screenshot, capture storage, and build the SSE event.

    Convenience wrapper that performs the full capture-and-serialize
    flow in one call.

    Args:
        session: Active browser session.
        storage: Pre-captured storage.  If ``None``, storage
            is captured from the session.
        extra: Optional additional fields for the event payload.

    Returns:
        Tuple of (SSE event string, raw JPEG bytes, captured storage).
    """
    try:
        screenshot_bytes = await session.take_screenshot(full_page=False)
    except Exception as exc:
        log.warn(
            "Screenshot failed in take_screenshot_event — using empty image",
            {"error": str(exc)},
        )
        screenshot_bytes = b""
    optimized = browser_session.BrowserSession.optimize_screenshot_bytes(screenshot_bytes)
    if storage is None:
        storage = await session.capture_storage()
    event_str = build_screenshot_event(session, optimized, storage, extra=extra)
    return event_str, screenshot_bytes, storage
