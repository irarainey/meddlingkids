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
        yield sse_helpers.format_sse_event("error", {"error": config_error})
        return

    valid_devices = list(device_configs.DEVICE_CONFIGS.keys())
    device_type = cast(
        browser.DeviceType,
        device if device in valid_devices else "ipad",
    )

    if not url:
        yield sse_helpers.format_sse_event(
            "error", {"error": "URL is required"}
        )
        return

    session = browser_session.BrowserSession()
    domain = url_mod.extract_domain(url)
    logger.start_log_file(domain)

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

            # ── Phase 4: Overlay Detection & Handling ───────────
            log.subsection("Phase 4: Overlay Detection & Handling")
            log.start_timer("overlay-handling")

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

            # Post-overlay capture
            yield sse_helpers.format_progress_event(
                "post-overlay-screenshot",
                "Capturing final page state...",
                72,
            )
            await session.capture_current_cookies()
            event_str, _, storage = await sse_helpers.take_screenshot_event(session)
            yield event_str

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
                    "Could not dismiss page overlay",
                    100,
                )
                return

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
            nav_result.error_message or "Failed to load page",
            100,
        ),
    ]
