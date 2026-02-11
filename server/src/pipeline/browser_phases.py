"""
Browser setup, navigation, page-load, access-check, and initial
data capture phases (Phases 1-3 of the analysis pipeline).
"""

from __future__ import annotations

from urllib import parse

from src.pipeline.sse_helpers import (
    format_progress_event,
    format_sse_event,
    take_screenshot_event,
)
from src.browser import session as browser_session
from src.models import browser
from src.utils import logger

log = logger.create_logger("Browser")


# ====================================================================
# Phase 1 — Browser Setup and Navigation
# ====================================================================


async def setup_and_navigate(
    session: browser_session.BrowserSession,
    url: str,
    device_type: browser.DeviceType,
) -> tuple[list[str], browser.NavigationResult]:
    """Launch browser and navigate to *url*.

    Returns:
        Tuple of (list of SSE event strings, NavigationResult).
    """
    events: list[str] = []
    hostname = parse.urlparse(url).hostname or url

    session.clear_tracking_data()
    session.set_current_page_url(url)

    log.start_timer("browser-launch")
    events.append(
        format_progress_event("browser", "Launching browser...", 8)
    )
    await session.launch_browser(device_type)
    log.end_timer("browser-launch", "Browser launched")

    log.start_timer("navigation")
    log.info("Navigating to page", {"hostname": hostname})
    events.append(
        format_progress_event(
            "navigate", f"Connecting to {hostname}...", 12
        )
    )

    nav_result = await session.navigate_to(
        url, "domcontentloaded", 30000
    )
    log.end_timer("navigation", "Initial navigation complete")
    log.info(
        "Navigation result",
        {
            "success": nav_result.success,
            "statusCode": nav_result.status_code,
        },
    )
    return events, nav_result


# ====================================================================
# Phase 2 — Wait for Page Load and Check Access
# ====================================================================


async def wait_for_page_load(
    session: browser_session.BrowserSession,
    hostname: str,
) -> list[str]:
    """Wait for page to be visually ready after DOM content loaded.

    Uses a short network-idle race (3 s) rather than a long timeout.
    Ad-heavy sites have continuous background traffic that never
    settles, so blocking on full network idle wastes tens of seconds
    without benefit.  The DOM and critical resources are already
    available after ``domcontentloaded``; a brief grace period is
    enough for consent banners, overlays, and initial ads to render.

    Returns:
        List of SSE progress event strings.
    """
    events: list[str] = []

    log.start_timer("network-idle")
    events.append(
        format_progress_event(
            "wait-network", f"Waiting for {hostname} to settle...", 18
        )
    )

    # Short race: give the page 3 s to reach network idle.
    # If it doesn't (ad-heavy sites), that's fine — proceed anyway.
    network_idle = await session.wait_for_network_idle(3000)
    log.end_timer("network-idle", "Network idle wait complete")

    if network_idle:
        log.success("Network became idle")
        events.append(
            format_progress_event(
                "wait-done", "Page fully loaded", 25
            )
        )
    else:
        log.info(
            "Network still active (normal for ad-heavy sites),"
            " proceeding with loaded DOM"
        )
        events.append(
            format_progress_event(
                "wait-continue",
                "Page loaded, continuing...",
                25,
            )
        )

    # Brief grace period for consent banners and overlays to render.
    events.append(
        format_progress_event(
            "wait-overlays", "Checking for page overlays...", 28
        )
    )
    await session.wait_for_timeout(2000)
    return events


async def check_access(
    session: browser_session.BrowserSession,
    nav_result: browser.NavigationResult,
) -> tuple[list[str], bool]:
    """Check whether the target site blocked our request.

    Returns:
        Tuple of (SSE event strings, access_denied flag).
        When ``access_denied`` is ``True`` the caller should abort.
    """
    events: list[str] = []

    log.start_timer("access-check")
    access_check = await session.check_for_access_denied()
    log.end_timer("access-check", "Access check complete")

    if not access_check.denied:
        return events, False

    log.error(
        "Access denied detected", {"reason": access_check.reason}
    )

    event_str, _, _ = await take_screenshot_event(
        session,
        storage={
            "local_storage": [],
            "session_storage": [],
        },
    )
    events.append(event_str)

    events.append(
        format_sse_event(
            "pageError",
            {
                "type": "access-denied",
                "statusCode": nav_result.status_code,
                "message": (
                    "Access denied - this site has bot protection"
                    " that blocked our request"
                ),
                "isAccessDenied": True,
                "reason": access_check.reason,
            },
        )
    )
    events.append(
        format_progress_event(
            "blocked", "Site blocked access", 100
        )
    )
    return events, True


# ====================================================================
# Phase 3 — Initial Data Capture
# ====================================================================


async def capture_initial_data(
    session: browser_session.BrowserSession,
) -> tuple[list[str], bytes, dict]:
    """Capture cookies, storage, and take the first screenshot.

    Returns:
        Tuple of (SSE events, screenshot PNG bytes, storage dict).
    """
    events: list[str] = []
    log.start_timer("initial-capture")

    events.append(
        format_progress_event(
            "capture", "Collecting cookies and storage...", 32
        )
    )
    await session.capture_current_cookies()
    storage = await session.capture_storage()

    events.append(
        format_progress_event(
            "screenshot", "Taking screenshot...", 38
        )
    )

    event_str, screenshot_bytes, storage = (
        await take_screenshot_event(session, storage)
    )
    events.append(event_str)

    cookie_count = len(session.get_tracked_cookies())
    script_count = len(session.get_tracked_scripts())
    request_count = len(session.get_tracked_network_requests())

    log.end_timer("initial-capture", "Initial data captured")
    log.info(
        "Initial capture stats",
        {
            "cookies": cookie_count,
            "scripts": script_count,
            "requests": request_count,
            "localStorage": len(storage["local_storage"]),
            "sessionStorage": len(storage["session_storage"]),
        },
    )

    events.append(
        format_progress_event(
            "captured",
            "Initial data captured",
            42,
        )
    )
    return events, screenshot_bytes, storage
