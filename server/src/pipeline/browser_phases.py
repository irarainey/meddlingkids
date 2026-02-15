"""
Browser setup, navigation, page-load, access-check, and initial
data capture phases (Phases 1-3 of the analysis pipeline).

Each public function performs a single focused step and returns
its result without emitting SSE progress events.  The caller
(``stream.py``) yields progress events inline between calls so
they reach the client in real-time rather than being batched.
"""

from __future__ import annotations

import asyncio
from urllib import parse

from playwright import async_api

from src.browser import session as browser_session
from src.consent import constants
from src.models import browser
from src.pipeline import sse_helpers
from src.utils import logger

log = logger.create_logger("Browser")


# ====================================================================
# Phase 1 — Browser Setup and Navigation
# ====================================================================


def prepare_session(
    session: browser_session.BrowserSession,
    url: str,
) -> None:
    """Clear previous tracking data and register the target URL."""
    session.clear_tracking_data()
    session.set_current_page_url(url)


async def launch_browser(
    session: browser_session.BrowserSession,
    device_type: browser.DeviceType,
) -> None:
    """Launch the browser with *device_type* emulation."""
    log.start_timer("browser-launch")
    log.info("Launching browser", {"deviceType": device_type})
    await session.launch_browser(device_type)
    log.end_timer("browser-launch", "Browser launched")


async def navigate(
    session: browser_session.BrowserSession,
    url: str,
) -> browser.NavigationResult:
    """Navigate to *url* and return the navigation result."""
    hostname = parse.urlparse(url).hostname or url
    log.start_timer("navigation")
    log.info("Navigating to page", {"hostname": hostname})

    nav_result = await session.navigate_to(url, "domcontentloaded", 30000)
    log.end_timer("navigation", "Initial navigation complete")
    log.info(
        "Navigation result",
        {
            "success": nav_result.success,
            "statusCode": nav_result.status_code,
        },
    )
    return nav_result


# ====================================================================
# Consent Dialog Readiness
# ====================================================================

# Poll interval and max wait for consent dialog readiness.
_CONSENT_POLL_INTERVAL_MS = 500
_CONSENT_MAX_WAIT_MS = 8000
# Extra delay after buttons appear to let rendering finish.
_CONSENT_RENDER_SETTLE_MS = 1500


async def _wait_for_consent_dialog_ready(
    page: async_api.Page,
) -> None:
    """Wait for a consent dialog to become interactive and rendered.

    Consent dialogs loaded via iframes (Quantcast, OneTrust, etc.)
    often render their container/header before the buttons load.
    Even after button elements appear in the DOM they may not be
    visually painted yet (CSS/fonts still loading).  This function
    detects that scenario, polls until buttons are **visible**, then
    waits for the iframe to reach ``load`` state and adds a short
    rendering-settle delay.

    Does nothing if no consent iframe/container is detected.
    """
    # Check for consent-manager iframes
    consent_frames: list[async_api.Frame] = [f for f in page.frames if constants.is_consent_frame(f, page.main_frame)]

    # Also check for known containers in the main frame
    has_main_frame_container = False
    for sel in constants.CONSENT_CONTAINER_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                has_main_frame_container = True
                break
        except Exception:
            continue

    if not consent_frames and not has_main_frame_container:
        return  # No consent dialog detected — nothing to wait for

    log.debug(
        "Consent dialog container detected, waiting for buttons to load and render",
        {
            "consentFrames": len(consent_frames),
            "mainFrameContainer": has_main_frame_container,
        },
    )

    # Poll for buttons to become *visible* in the consent
    # frames and/or main-frame containers.
    frames_to_check = consent_frames if consent_frames else [page.main_frame]
    polls = _CONSENT_MAX_WAIT_MS // _CONSENT_POLL_INTERVAL_MS
    buttons_ready = False

    for attempt in range(polls):
        for frame in frames_to_check:
            try:
                buttons = frame.get_by_role("button")
                # Check that at least 2 buttons are both
                # present and *visible* (painted on screen).
                visible_count = 0
                total = await buttons.count()
                for i in range(min(total, 6)):
                    try:
                        if await buttons.nth(i).is_visible():
                            visible_count += 1
                    except Exception:
                        continue
                if visible_count >= 2:
                    log.debug(
                        "Consent dialog buttons visible",
                        {
                            "visible": visible_count,
                            "total": total,
                            "waitMs": (attempt * _CONSENT_POLL_INTERVAL_MS),
                        },
                    )
                    buttons_ready = True
                    break
            except Exception:
                continue
        if buttons_ready:
            break

        await asyncio.sleep(_CONSENT_POLL_INTERVAL_MS / 1000)

    if not buttons_ready:
        log.debug(
            "Consent dialog readiness wait exhausted — proceeding anyway",
            {"maxWaitMs": _CONSENT_MAX_WAIT_MS},
        )

    # Wait for consent iframe(s) to finish loading resources
    # (CSS, fonts, images) so the dialog is fully rendered
    # when the screenshot is taken.
    for frame in consent_frames:
        try:
            async with asyncio.timeout(3):
                await frame.wait_for_load_state("load")
            log.debug(
                "Consent frame reached load state",
                {"url": frame.url[:80]},
            )
        except (TimeoutError, Exception):
            pass

    # Final rendering-settle delay — even after load, the
    # browser may need a moment to paint the composited frame.
    await asyncio.sleep(_CONSENT_RENDER_SETTLE_MS / 1000)


# ====================================================================
# Phase 2 — Wait for Page Load and Check Access
# ====================================================================


async def wait_for_network_settle(
    session: browser_session.BrowserSession,
) -> None:
    """Wait up to 3 s for network activity to settle.

    Ad-heavy sites have continuous background traffic that never
    settles, so blocking on full network idle wastes tens of
    seconds without benefit.  The DOM and critical resources are
    already available after ``domcontentloaded``; a brief race is
    enough for the initial burst of requests to land.
    """
    log.start_timer("network-idle")
    network_idle = await session.wait_for_network_idle(3000)
    log.end_timer("network-idle", "Network idle wait complete")

    if network_idle:
        log.success("Network became idle")
    else:
        log.info("Network still active (normal for ad-heavy sites), proceeding with loaded DOM")


async def wait_for_content_render(
    session: browser_session.BrowserSession,
) -> None:
    """Brief grace period for consent banners and overlays to render.

    Waits 2 s for late-loading content, then checks whether a
    consent dialog container is present and waits for its buttons
    to become interactive.
    """
    await session.wait_for_timeout(2000)

    page = session.get_page()
    if page:
        await _wait_for_consent_dialog_ready(page)

    log.info("Page content rendering complete")


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

    log.error("Access denied detected", {"reason": access_check.reason})

    event_str, _, _ = await sse_helpers.take_screenshot_event(
        session,
        storage={
            "local_storage": [],
            "session_storage": [],
        },
    )
    events.append(event_str)

    events.append(
        sse_helpers.format_sse_event(
            "pageError",
            {
                "type": "access-denied",
                "statusCode": nav_result.status_code,
                "message": ("Access denied - this site has bot protection that blocked our request"),
                "isAccessDenied": True,
                "reason": access_check.reason,
            },
        )
    )
    events.append(sse_helpers.format_progress_event("blocked", "Site blocked access!", 100))
    return events, True


# ====================================================================
# Phase 3 — Initial Data Capture
# ====================================================================


async def capture_page_data(
    session: browser_session.BrowserSession,
) -> dict:
    """Capture cookies and storage.

    Returns:
        Storage dict with ``local_storage`` and ``session_storage``.
    """
    log.start_timer("initial-capture")
    await session.capture_current_cookies()
    return await session.capture_storage()


async def take_initial_screenshot(
    session: browser_session.BrowserSession,
    storage: dict,
) -> tuple[str, bytes, dict]:
    """Take the first page screenshot.

    Returns:
        Tuple of (SSE screenshot event, PNG bytes, storage dict).
    """
    return await sse_helpers.take_screenshot_event(session, storage)


def log_capture_stats(
    session: browser_session.BrowserSession,
    storage: dict,
) -> None:
    """Log initial capture statistics."""
    log.end_timer("initial-capture", "Initial data captured")
    log.info(
        "Initial capture stats",
        {
            "cookies": len(session.get_tracked_cookies()),
            "scripts": len(session.get_tracked_scripts()),
            "requests": len(session.get_tracked_network_requests()),
            "localStorage": len(storage["local_storage"]),
            "sessionStorage": len(storage["session_storage"]),
        },
    )
