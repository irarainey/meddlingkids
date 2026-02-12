"""
Streaming URL analysis endpoint.

Thin orchestrator that delegates each phase to a focused module:

- ``browser_phases`` — browser setup, navigation, page load, access check,
  initial data capture (Phases 1–3)
- ``overlay_pipeline`` — overlay detection, DOM validation, click,
  consent extraction (Phase 4)
- ``analysis_pipeline`` — concurrent AI analysis, scoring, summary
  (Phase 5)
- ``sse_helpers`` — SSE formatting, serialization, screenshot builders
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import AsyncGenerator, cast
from urllib import parse

from src.agents import config
from src.browser import device_configs, session as browser_session
from src.models import browser
from src.pipeline import (
    analysis_pipeline,
    browser_phases,
    overlay_pipeline,
    sse_helpers,
)
from src.utils import errors, logger
from src.utils import url as url_mod

log = logger.create_logger("Analyze")

# Maximum wall-clock time (seconds) for a single analysis run.
# Prevents runaway sessions from holding browser resources
# indefinitely.  Individual phases may finish faster; this is
# the outer safety net.
STREAM_TIMEOUT_SECONDS = 600  # 10 minutes

# How often (seconds) the background refresher checks for
# visual changes on the page.  Keeping this short enough
# to catch ads loading but long enough to avoid excessive
# screenshot overhead.
_REFRESH_INTERVAL_SECONDS = 3.0


async def _screenshot_refresher(
    session: browser_session.BrowserSession,
    queue: asyncio.Queue[str],
    last_hash: str,
) -> None:
    """Periodically re-screenshot the page and queue update events.

    Runs as a background task.  Every ``_REFRESH_INTERVAL_SECONDS``
    it takes a new screenshot, hashes it, and — if the page has
    visually changed — pushes a lightweight ``screenshotUpdate``
    SSE event into *queue* so the main generator can yield it.

    The task runs until cancelled by the caller (e.g. just before
    a "real" screenshot is about to be emitted).

    Args:
        session: Active browser session.
        queue: Asyncio queue for outbound SSE event strings.
        last_hash: MD5 hex digest of the most recent screenshot
            bytes so we can skip identical frames.
    """
    current_hash = last_hash
    while True:
        await asyncio.sleep(_REFRESH_INTERVAL_SECONDS)
        try:
            png_bytes = await session.take_screenshot(full_page=False)
            new_hash = hashlib.md5(png_bytes).hexdigest()  # noqa: S324
            if new_hash != current_hash:
                current_hash = new_hash
                optimized = (
                    browser_session.BrowserSession
                    .optimize_screenshot_bytes(png_bytes)
                )
                event = sse_helpers.format_screenshot_update_event(
                    optimized,
                )
                await queue.put(event)
                log.debug("Screenshot refreshed (page changed)")
        except asyncio.CancelledError:
            raise
        except Exception:
            # Screenshot failed (page navigating, etc.) — skip
            pass


def _drain_queue(queue: asyncio.Queue[str]) -> list[str]:
    """Drain all currently-queued events without blocking."""
    events: list[str] = []
    while not queue.empty():
        try:
            events.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return events


async def analyze_url_stream(
    url: str, device: str = "ipad"
) -> AsyncGenerator[str, None]:
    """Analyze tracking on a URL with streaming progress via SSE.

    Opens a browser, navigates to the URL, detects and handles
    cookie consent banners, captures tracking data, and runs AI
    analysis.  Progress is streamed via Server-Sent Events.

    Each call creates its own isolated ``BrowserSession``,
    enabling concurrent analyses without interference.
    """
    # ── Pre-flight validation ───────────────────────────────
    config_error = config.validate_llm_config()
    if config_error:
        log.error("LLM configuration error", {"error": config_error})
        yield sse_helpers.format_sse_event("error", {"error": config_error})
        return

    valid_devices = list(device_configs.DEVICE_CONFIGS.keys())
    device_type = cast(
        browser.DeviceType,
        device if device in valid_devices else "ipad",
    )
    if device not in valid_devices:
        log.warn(f"Invalid device type '{device}', defaulting to 'ipad'")

    if not url:
        yield sse_helpers.format_sse_event(
            "error", {"error": "URL is required"}
        )
        return

    session = browser_session.BrowserSession()
    domain = url_mod.extract_domain(url)
    logger.start_log_file(domain)
    refresher_task: asyncio.Task[None] | None = None

    log.section(f"Analyzing: {url}")
    log.info("Request received", {"url": url, "device": device_type})
    log.start_timer("total-analysis")

    try:
        async with asyncio.timeout(STREAM_TIMEOUT_SECONDS):
            # ── Phase 1: Browser Setup & Navigation ─────────────
            log.subsection("Phase 1: Browser Setup")
            yield sse_helpers.format_progress_event("init", "Checking configuration...", 5)

            nav_events, nav_result = (
                await browser_phases.setup_and_navigate(
                    session, url, device_type
                )
            )
            for event in nav_events:
                yield event

            if not nav_result.success:
                for event in _emit_nav_failure(nav_result):
                    yield event
                return

            hostname = parse.urlparse(url).hostname or url

            # ── Phase 2: Page Load & Access Check ───────────────
            log.subsection("Phase 2: Page Load & Access Check")
            for event in await browser_phases.wait_for_page_load(
                session, hostname
            ):
                yield event

            access_events, denied = await browser_phases.check_access(
                session, nav_result
            )
            for event in access_events:
                yield event
            if denied:
                return

            # ── Phase 3: Initial Data Capture ───────────────────
            log.subsection("Phase 3: Initial Data Capture")
            capture_events, screenshot, storage = (
                await browser_phases.capture_initial_data(session)
            )
            for event in capture_events:
                yield event

            # Start background screenshot refresher so the
            # client sees ads and deferred content as they load.
            refresh_queue: asyncio.Queue[str] = asyncio.Queue()
            initial_hash = hashlib.md5(screenshot).hexdigest()  # noqa: S324
            refresher_task = asyncio.create_task(
                _screenshot_refresher(session, refresh_queue, initial_hash)
            )
            log.debug("Background screenshot refresher started")

            # ── Phase 4: Overlay Detection & Handling ───────────
            log.subsection("Phase 4: Overlay Detection & Handling")
            log.start_timer("overlay-handling")

            # Stop the background screenshot refresher before
            # overlay handling so the initial screenshot
            # (showing the consent dialog) is preserved in the
            # client gallery.  The overlay pipeline will emit
            # its own post-click screenshots.
            refresher_task.cancel()
            try:
                await refresher_task
            except asyncio.CancelledError:
                pass
            log.debug(
                "Background screenshot refresher paused"
                " for overlay handling"
            )
            # Flush any remaining refresh events queued
            # before the task was cancelled.
            for refresh_event in _drain_queue(refresh_queue):
                yield refresh_event

            page = session.get_page()
            consent_details = None
            overlay_count = 0

            if page:
                pipeline = overlay_pipeline.OverlayPipeline(
                    session, page, screenshot
                )
                async for event in pipeline.run():
                    yield event
                overlay_result = pipeline.result
                consent_details = overlay_result.consent_details
                overlay_count = overlay_result.overlay_count
                storage = overlay_result.final_storage
            else:
                overlay_result = (
                    overlay_pipeline.OverlayHandlingResult()
                )

            log.end_timer(
                "overlay-handling", "Overlay handling complete"
            )
            log.info(
                "Overlay handling result",
                {
                    "overlaysFound": overlay_count,
                    "hasConsentDetails": consent_details is not None,
                },
            )

            # Post-overlay capture — only emit a new screenshot
            # when no overlays were dismissed.  The overlay
            # pipeline already emits a screenshot after every
            # successful dismiss, so taking another one here
            # would just duplicate the last image.

            if overlay_count == 0:
                yield sse_helpers.format_progress_event(
                    "post-overlay-screenshot",
                    "Capturing final page state...",
                    72,
                )
                await session.capture_current_cookies()
                event_str, _, storage = (
                    await sse_helpers.take_screenshot_event(session)
                )
                yield event_str
            else:
                # Still refresh cookies/storage for analysis,
                # but don't emit a redundant screenshot event.
                await session.capture_current_cookies()
                storage = await session.capture_storage()

            if page and overlay_result.failed:
                log.error(
                    "Overlay dismissal failed, aborting analysis",
                    {"reason": overlay_result.failure_message},
                )
                yield sse_helpers.format_sse_event(
                    "pageError",
                    {
                        "type": "overlay-blocked",
                        "message": overlay_result.failure_message,
                        "isOverlayBlocked": True,
                    },
                )
                yield sse_helpers.format_progress_event(
                    "overlay-blocked",
                    "Could not dismiss page overlay!",
                    100,
                )
                return

            # Restart the background screenshot refresher so the
            # client sees visual changes during AI analysis
            # (e.g. ads loading, deferred content).
            refresh_queue = asyncio.Queue()
            refresher_task = asyncio.create_task(
                _screenshot_refresher(session, refresh_queue, "")
            )
            log.debug("Background screenshot refresher resumed")

            # ── Phase 5: AI Analysis ────────────────────────────
            log.subsection("Phase 5: AI Analysis")

            async for event in analysis_pipeline.run_ai_analysis(
                session,
                storage,
                url,
                consent_details,
                overlay_count,
            ):
                yield event
                # Interleave any pending screenshot updates
                for refresh_event in _drain_queue(refresh_queue):
                    yield refresh_event

            # Drain any remaining refresh events after analysis
            for refresh_event in _drain_queue(refresh_queue):
                yield refresh_event

            # ── Phase 6: Complete ───────────────────────────────
            total_time = log.end_timer(
                "total-analysis", "Analysis complete"
            )
            log.success(
                "Investigation complete!",
                {
                    "totalTime": f"{(total_time / 1000):.2f}s",
                    "overlaysDismissed": overlay_count,
                },
            )

    except TimeoutError:
        log.error(
            "Analysis timed out",
            {"timeout_seconds": STREAM_TIMEOUT_SECONDS},
        )
        yield sse_helpers.format_sse_event(
            "error",
            {
                "error": (
                    f"Analysis timed out after"
                    f" {STREAM_TIMEOUT_SECONDS // 60} minutes"
                ),
            },
        )
    except Exception as error:
        log.error(
            "Analysis failed with exception",
            {"error": errors.get_error_message(error)},
        )
        yield sse_helpers.format_sse_event(
            "error",
            {"error": errors.get_error_message(error)},
        )
    finally:
        # Cancel the background screenshot refresher if it's
        # still running (e.g. due to an early return or error).
        if refresher_task and not refresher_task.done():
            refresher_task.cancel()
            try:
                await refresher_task
            except asyncio.CancelledError:
                pass
        log.debug("Cleaning up browser resources...")
        try:
            await session.close()
        except Exception as err:
            log.warn(
                "Error during browser cleanup",
                {"error": errors.get_error_message(err)},
            )
        log.debug("Browser cleanup complete")
        logger.end_log_file()


def _emit_nav_failure(
    nav_result: browser.NavigationResult,
) -> list[str]:
    """Build SSE events for a navigation failure."""
    error_type = (
        "access-denied"
        if nav_result.is_access_denied
        else "server-error"
    )
    log.error(
        "Navigation failed",
        {
            "errorType": error_type,
            "statusCode": nav_result.status_code,
        },
    )
    return [
        sse_helpers.format_sse_event(
            "pageError",
            {
                "type": error_type,
                "statusCode": nav_result.status_code,
                "message": nav_result.error_message,
                "isAccessDenied": nav_result.is_access_denied,
            },
        ),
        sse_helpers.format_progress_event(
            "error",
            nav_result.error_message or "Failed to load page!",
            100,
        ),
    ]
