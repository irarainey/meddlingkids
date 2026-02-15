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
import contextlib
import hashlib
from collections.abc import AsyncGenerator
from typing import cast
from urllib import parse

from src.agents import config
from src.analysis import tracking_summary
from src.browser import device_configs
from src.browser import session as browser_session
from src.models import browser
from src.pipeline import analysis_pipeline, browser_phases, overlay_pipeline, sse_helpers
from src.utils import cache, errors, logger, usage_tracking
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

# Maximum screenshot updates per stage.  Each pipeline stage
# (page load, analysis) gets its own fresh cap so the UI stays
# responsive throughout the run.
_MAX_SCREENSHOT_REFRESHES = 3


async def _screenshot_refresher(
    session: browser_session.BrowserSession,
    queue: asyncio.Queue[str],
    last_hash: str,
    remaining: int = _MAX_SCREENSHOT_REFRESHES,
) -> None:
    """Periodically re-screenshot the page and queue update events.

    Runs as a background task.  Every ``_REFRESH_INTERVAL_SECONDS``
    it takes a new screenshot, hashes it, and — if the page has
    visually changed — pushes a lightweight ``screenshotUpdate``
    SSE event into *queue* so the main generator can yield it.

    The task stops automatically after *remaining* updates have
    been emitted, or when cancelled by the caller.

    Args:
        session: Active browser session.
        queue: Asyncio queue for outbound SSE event strings.
        last_hash: MD5 hex digest of the most recent screenshot
            bytes so we can skip identical frames.
        remaining: Maximum number of screenshot updates to emit
            before the task exits on its own.
    """
    current_hash = last_hash
    updates_sent = 0
    while updates_sent < remaining:
        await asyncio.sleep(_REFRESH_INTERVAL_SECONDS)
        try:
            png_bytes = await session.take_screenshot(full_page=False)
            new_hash = hashlib.md5(png_bytes).hexdigest()
            if new_hash != current_hash:
                current_hash = new_hash
                optimized = browser_session.BrowserSession.optimize_screenshot_bytes(png_bytes)
                event = sse_helpers.format_screenshot_update_event(
                    optimized,
                )
                await queue.put(event)
                updates_sent += 1
                log.debug(
                    "Screenshot refreshed (page changed)",
                    {"update": updates_sent, "limit": remaining},
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Screenshot failed (page navigating, etc.) — skip
            pass
    log.debug(
        "Screenshot refresher stopped (limit reached)",
        {"updates": updates_sent},
    )


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
    url: str,
    device: str = "ipad",
    *,
    clear_cache: bool = False,
) -> AsyncGenerator[str]:
    """Analyze tracking on a URL with streaming progress via SSE.

    Opens a browser, navigates to the URL, detects and handles
    cookie consent banners, captures tracking data, and runs AI
    analysis.  Progress is streamed via Server-Sent Events.

    Each call creates its own isolated ``BrowserSession``,
    enabling concurrent analyses without interference.

    Args:
        url: The URL to analyze.
        device: Device type to emulate.
        clear_cache: When ``True``, delete all cache files
            (domain, overlay, scripts) before starting.
    """
    if clear_cache:
        cache.clear_all()
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
        log.warn("Invalid device type, defaulting to 'ipad'", {"device": device})

    if not url:
        yield sse_helpers.format_sse_event("error", {"error": "URL is required"})
        return

    session = browser_session.BrowserSession()
    domain = url_mod.extract_domain(url)
    logger.clear_log_buffer()
    logger.start_log_file(domain)
    refresher_task: asyncio.Task[None] | None = None

    usage_tracking.reset()
    log.section(f"Analyzing: {url}")
    log.info("Request received", {"url": url, "device": device_type})
    log.start_timer("total-analysis")

    try:
        async with asyncio.timeout(STREAM_TIMEOUT_SECONDS):
            # ── Phase 1: Browser Setup & Navigation ─────────────
            log.subsection("Phase 1: Browser Setup")
            log.info("Initializing browser", {"url": url, "device": device_type})
            yield sse_helpers.format_progress_event("init", "Warming up the browser...", 5)

            browser_phases.prepare_session(session, url)

            yield sse_helpers.format_progress_event("browser", "Launching browser...", 8)
            await browser_phases.launch_browser(session, device_type)

            hostname = parse.urlparse(url).hostname or url

            yield sse_helpers.format_progress_event("navigate", f"Loading {hostname}...", 12)
            nav_result = await browser_phases.navigate(session, url)

            if not nav_result.success:
                for event in _emit_nav_failure(nav_result):
                    yield event
                return

            # Start Stage 1 screenshot refresher — captures
            # visual changes while the page loads (fonts,
            # images, layout shifts, ad placements).  Each
            # stage gets its own refresh cap.
            refresh_queue: asyncio.Queue[str] = asyncio.Queue()
            try:
                initial_png = await session.take_screenshot(full_page=False)
                last_screenshot_hash = hashlib.md5(initial_png).hexdigest()
            except Exception:
                last_screenshot_hash = ""
            refresher_task = asyncio.create_task(_screenshot_refresher(session, refresh_queue, last_screenshot_hash))
            log.debug("Stage 1 screenshot refresher started")

            # ── Phase 2: Page Load & Access Check ───────────────
            log.subsection("Phase 2: Page Load & Access Check")

            yield sse_helpers.format_progress_event("wait-network", f"Waiting for {hostname} to settle...", 18)
            await browser_phases.wait_for_network_settle(session)

            yield sse_helpers.format_progress_event("wait-content", "Waiting for page content to render...", 25)
            await browser_phases.wait_for_content_render(session)

            for refresh_event in _drain_queue(refresh_queue):
                yield refresh_event

            access_events, denied = await browser_phases.check_access(session, nav_result)
            for event in access_events:
                yield event
            for refresh_event in _drain_queue(refresh_queue):
                yield refresh_event
            if denied:
                return

            # ── Phase 3: Initial Data Capture ───────────────────
            log.subsection("Phase 3: Initial Data Capture")

            yield sse_helpers.format_progress_event("capture", "Capturing page data...", 32)
            storage = await browser_phases.capture_page_data(session)

            yield sse_helpers.format_progress_event("screenshot", "Capturing page screenshot...", 38)
            screenshot_event, screenshot, storage = await browser_phases.take_initial_screenshot(session, storage)
            yield screenshot_event

            browser_phases.log_capture_stats(session, storage)

            yield sse_helpers.format_progress_event("overlay-detect", "Detecting page overlays...", 42)

            # Cancel Stage 1 refresher — the initial capture
            # provides the authoritative page state from here.
            if refresher_task and not refresher_task.done():
                refresher_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await refresher_task
            for refresh_event in _drain_queue(refresh_queue):
                yield refresh_event
            log.debug("Stage 1 screenshot refresher ended")

            # Snapshot page-load data and classify what is
            # actually tracking vs legitimate infrastructure.
            # This runs before any overlay is dismissed —
            # some overlays (e.g. sign-in prompts) may not
            # be consent-related.  We cannot determine from
            # this snapshot whether scripts use the cookies
            # present, whether a dialog is a consent dialog,
            # or whether the activity is covered by consent.
            pre_consent_stats = tracking_summary.build_pre_consent_stats(
                session.get_tracked_cookies(),
                session.get_tracked_scripts(),
                session.get_tracked_network_requests(),
                storage,
            )

            # Tag every request captured so far as pre-consent.
            # Requests arriving after this point (during or
            # after overlay/consent handling) will keep the
            # default pre_consent=False.
            for req in session.get_tracked_network_requests():
                req.pre_consent = True

            # ── Phase 4: Overlay Detection & Handling ───────────
            log.subsection("Phase 4: Overlay Detection & Handling")
            log.start_timer("overlay-handling")

            page = session.get_page()
            consent_details = None
            overlay_count = 0

            if page:
                pipeline = overlay_pipeline.OverlayPipeline(session, page, screenshot, domain=domain)
                async for event in pipeline.run():
                    yield event
                overlay_result = pipeline.result
                consent_details = overlay_result.consent_details
                overlay_count = overlay_result.overlay_count
                storage = overlay_result.final_storage
            else:
                overlay_result = overlay_pipeline.OverlayHandlingResult()

            log.end_timer("overlay-handling", "Overlay handling complete")
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
            #
            # When no overlays were found the pipeline already
            # emitted "No overlay detected..." at 70%.  Let
            # that message stay visible while we silently
            # capture the authoritative page state.

            if overlay_count == 0:
                log.info("No overlays dismissed — capturing final page state")
                await session.capture_current_cookies()
                event_str, _, storage = await sse_helpers.take_screenshot_event(session)
                yield event_str
            else:
                # Still refresh cookies/storage for analysis,
                # but don't emit a redundant screenshot event.
                await session.capture_current_cookies()
                storage = await session.capture_storage()

            if page and overlay_result.failed:
                # If consent data was still captured (pre-click
                # text preserved despite click failure), continue
                # analysis so the report includes consent info.
                if consent_details:
                    log.warn(
                        "Overlay click failed but consent data preserved — continuing analysis",
                        {
                            "categories": len(consent_details.categories),
                            "partners": len(consent_details.partners),
                        },
                    )
                else:
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

            # ── Post-overlay stabilisation ──────────────────
            # After dismissing an overlay, sites typically
            # fire a burst of deferred tracking scripts (ad
            # loaders, analytics, pixels) that were held
            # back pending user interaction.  A brief
            # network-idle race gives them time to arrive
            # so the analysis sees a consistent set of
            # scripts regardless of network jitter.
            if overlay_count > 0:
                log.start_timer("post-overlay-settle")
                yield sse_helpers.format_progress_event(
                    "post-overlay-settle",
                    "Waiting for page to settle...",
                    73,
                )
                settled = await session.wait_for_network_idle(5000)
                log.end_timer(
                    "post-overlay-settle",
                    f"Post-overlay settle ({'idle' if settled else 'timeout'})",
                )

            # ── Stage 2 screenshot refresher ────────────────
            # Fresh cap for the analysis phase so the client
            # sees visual changes (ads loading, deferred
            # content) independently of Stage 1's quota.
            remaining_refreshes = _MAX_SCREENSHOT_REFRESHES
            current_hash = ""

            # Take an immediate screenshot — the page has
            # very likely changed after page load, consent
            # dismissal, and post-consent script loading.
            if remaining_refreshes > 0:
                try:
                    png = await session.take_screenshot(full_page=False)
                    current_hash = hashlib.md5(png).hexdigest()
                    optimized = browser_session.BrowserSession.optimize_screenshot_bytes(png)
                    yield sse_helpers.format_screenshot_update_event(
                        optimized,
                    )
                    remaining_refreshes -= 1
                    log.info("Immediate pre-analysis screenshot refresh emitted")
                except Exception:
                    pass

            refresh_queue = asyncio.Queue()
            if remaining_refreshes > 0:
                refresher_task = asyncio.create_task(
                    _screenshot_refresher(
                        session,
                        refresh_queue,
                        current_hash,
                        remaining=remaining_refreshes,
                    )
                )
                log.debug(
                    "Stage 2 screenshot refresher started",
                    {"remaining": remaining_refreshes},
                )
            else:
                refresher_task = None

            # ── Phase 5: AI Analysis ────────────────────────────
            log.subsection("Phase 5: AI Analysis")

            async for event in analysis_pipeline.run_ai_analysis(
                session,
                storage,
                url,
                consent_details,
                overlay_count,
                pre_consent_stats,
            ):
                yield event
                # Interleave any pending screenshot updates
                for refresh_event in _drain_queue(refresh_queue):
                    yield refresh_event

            # Stop the refresher now that analysis is done —
            # no value in updating screenshots after this point.
            if refresher_task and not refresher_task.done():
                refresher_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await refresher_task
            # Drain any remaining refresh events after analysis
            for refresh_event in _drain_queue(refresh_queue):
                yield refresh_event

            # ── Phase 6: Complete ───────────────────────────────
            usage_tracking.log_summary()
            total_time = log.end_timer("total-analysis", "Analysis complete")
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
                "error": (f"Analysis timed out after {STREAM_TIMEOUT_SECONDS // 60} minutes"),
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
            with contextlib.suppress(asyncio.CancelledError):
                await refresher_task
        log.debug("Cleaning up browser resources...")
        logger.end_log_file()
        try:
            await session.close()
        except Exception as err:
            log.warn(
                "Error during browser cleanup",
                {"error": errors.get_error_message(err)},
            )
        log.debug("Browser cleanup complete")


def _emit_nav_failure(
    nav_result: browser.NavigationResult,
) -> list[str]:
    """Build SSE events for a navigation failure."""
    error_type = "access-denied" if nav_result.is_access_denied else "server-error"
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
