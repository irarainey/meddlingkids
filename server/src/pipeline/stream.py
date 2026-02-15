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
import dataclasses
import hashlib
from collections.abc import AsyncGenerator
from typing import cast
from urllib import parse

from src.agents import config
from src.analysis import tracking_summary
from src.browser import device_configs
from src.browser import session as browser_session
from src.models import analysis, browser, consent
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


# ====================================================================
# Shared context for the streaming pipeline
# ====================================================================


@dataclasses.dataclass
class _StreamContext:
    """Mutable state shared across streaming pipeline phases."""

    session: browser_session.BrowserSession
    url: str
    hostname: str
    domain: str
    device_type: browser.DeviceType
    refresher_task: asyncio.Task[None] | None = None
    refresh_queue: asyncio.Queue[str] = dataclasses.field(default_factory=asyncio.Queue)
    storage: dict = dataclasses.field(default_factory=dict)
    screenshot: bytes = b""
    pre_consent_stats: analysis.PreConsentStats | None = None
    consent_details: consent.ConsentDetails | None = None
    overlay_count: int = 0
    overlay_result: overlay_pipeline.OverlayHandlingResult | None = None
    aborted: bool = False


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
            log.debug("Screenshot refresh failed (page navigating, etc.) — skipping")
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
    hostname = parse.urlparse(url).hostname or url
    logger.clear_log_buffer()
    logger.start_log_file(domain)

    ctx = _StreamContext(
        session=session,
        url=url,
        hostname=hostname,
        domain=domain,
        device_type=device_type,
    )

    usage_tracking.reset()
    log.section(f"Analyzing: {url}")
    log.info("Request received", {"url": url, "device": device_type})
    log.start_timer("total-analysis")

    try:
        async with asyncio.timeout(STREAM_TIMEOUT_SECONDS):
            async for event in _run_phases_1_to_3(ctx):
                yield event
            if ctx.aborted:
                return

            async for event in _run_phase_4_overlays(ctx):
                yield event
            if ctx.aborted:
                return

            async for event in _run_phase_5_analysis(ctx):
                yield event

            # ── Phase 6: Complete ───────────────────────────────
            usage_tracking.log_summary()
            total_time = log.end_timer("total-analysis", "Analysis complete")
            log.success(
                "Investigation complete!",
                {
                    "totalTime": f"{(total_time / 1000):.2f}s",
                    "overlaysDismissed": ctx.overlay_count,
                },
            )

    except TimeoutError:
        log.error(
            "Analysis timed out",
            {"timeout_seconds": STREAM_TIMEOUT_SECONDS},
        )
        yield sse_helpers.format_sse_event(
            "error",
            {"error": f"Analysis timed out after {STREAM_TIMEOUT_SECONDS // 60} minutes"},
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
        if ctx.refresher_task and not ctx.refresher_task.done():
            ctx.refresher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ctx.refresher_task
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


# ====================================================================
# Phase helpers — each yields SSE events and mutates ctx
# ====================================================================


async def _run_phases_1_to_3(ctx: _StreamContext) -> AsyncGenerator[str]:
    """Phases 1–3: browser setup, navigation, page load, data capture.

    Sets ``ctx.aborted`` if navigation fails or access is denied.
    Populates ``ctx.storage``, ``ctx.screenshot``, and
    ``ctx.pre_consent_stats``.
    """
    session = ctx.session

    # ── Phase 1: Browser Setup & Navigation ─────────────
    log.subsection("Phase 1: Browser Setup")
    log.info("Initializing browser", {"url": ctx.url, "device": ctx.device_type})
    yield sse_helpers.format_progress_event("init", "Warming up the browser...", 5)

    browser_phases.prepare_session(session, ctx.url)

    yield sse_helpers.format_progress_event("browser", "Launching browser...", 8)
    await browser_phases.launch_browser(session, ctx.device_type)

    yield sse_helpers.format_progress_event("navigate", f"Loading {ctx.hostname}...", 12)
    nav_result = await browser_phases.navigate(session, ctx.url)

    if not nav_result.success:
        for event in _emit_nav_failure(nav_result):
            yield event
        ctx.aborted = True
        return

    # Start Stage 1 screenshot refresher — captures
    # visual changes while the page loads.
    ctx.refresh_queue = asyncio.Queue()
    try:
        initial_png = await session.take_screenshot(full_page=False)
        last_screenshot_hash = hashlib.md5(initial_png).hexdigest()
    except Exception:
        log.debug("Initial screenshot for hash failed — starting refresher with empty hash")
        last_screenshot_hash = ""
    ctx.refresher_task = asyncio.create_task(
        _screenshot_refresher(session, ctx.refresh_queue, last_screenshot_hash),
    )
    log.debug("Stage 1 screenshot refresher started")

    # ── Phase 2: Page Load & Access Check ───────────────
    log.subsection("Phase 2: Page Load & Access Check")

    yield sse_helpers.format_progress_event("wait-network", f"Waiting for {ctx.hostname} to settle...", 18)
    await browser_phases.wait_for_network_settle(session)

    yield sse_helpers.format_progress_event("wait-content", "Waiting for page content to render...", 25)
    await browser_phases.wait_for_content_render(session)

    for refresh_event in _drain_queue(ctx.refresh_queue):
        yield refresh_event

    access_events, denied = await browser_phases.check_access(session, nav_result)
    for event in access_events:
        yield event
    for refresh_event in _drain_queue(ctx.refresh_queue):
        yield refresh_event
    if denied:
        ctx.aborted = True
        return

    # ── Phase 3: Initial Data Capture ───────────────────
    log.subsection("Phase 3: Initial Data Capture")

    yield sse_helpers.format_progress_event("capture", "Capturing page data...", 32)
    ctx.storage = await browser_phases.capture_page_data(session)

    yield sse_helpers.format_progress_event("screenshot", "Capturing page screenshot...", 38)
    screenshot_event, ctx.screenshot, ctx.storage = await browser_phases.take_initial_screenshot(
        session,
        ctx.storage,
    )
    yield screenshot_event

    browser_phases.log_capture_stats(session, ctx.storage)

    yield sse_helpers.format_progress_event("overlay-detect", "Detecting page overlays...", 42)

    # Cancel Stage 1 refresher — the initial capture
    # provides the authoritative page state from here.
    if ctx.refresher_task and not ctx.refresher_task.done():
        ctx.refresher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ctx.refresher_task
    for refresh_event in _drain_queue(ctx.refresh_queue):
        yield refresh_event
    log.debug("Stage 1 screenshot refresher ended")

    # Snapshot page-load data before any overlay is dismissed.
    ctx.pre_consent_stats = tracking_summary.build_pre_consent_stats(
        session.get_tracked_cookies(),
        session.get_tracked_scripts(),
        session.get_tracked_network_requests(),
        ctx.storage,
    )

    # Tag every request captured so far as pre-consent.
    for req in session.get_tracked_network_requests():
        req.pre_consent = True


async def _run_phase_4_overlays(ctx: _StreamContext) -> AsyncGenerator[str]:
    """Phase 4: overlay detection, dismissal, and post-overlay capture.

    Sets ``ctx.aborted`` if overlay dismissal fails fatally.
    Populates ``ctx.consent_details``, ``ctx.overlay_count``,
    ``ctx.overlay_result``, and updates ``ctx.storage``.
    """
    session = ctx.session

    log.subsection("Phase 4: Overlay Detection & Handling")
    log.start_timer("overlay-handling")

    page = session.get_page()

    if page:
        pipeline = overlay_pipeline.OverlayPipeline(
            session,
            page,
            ctx.screenshot,
            domain=ctx.domain,
        )
        async for event in pipeline.run():
            yield event
        ctx.overlay_result = pipeline.result
        ctx.consent_details = ctx.overlay_result.consent_details
        ctx.overlay_count = ctx.overlay_result.overlay_count
        ctx.storage = ctx.overlay_result.final_storage
    else:
        ctx.overlay_result = overlay_pipeline.OverlayHandlingResult()

    log.end_timer("overlay-handling", "Overlay handling complete")
    log.info(
        "Overlay handling result",
        {
            "overlaysFound": ctx.overlay_count,
            "hasConsentDetails": ctx.consent_details is not None,
        },
    )

    # Post-overlay capture — only emit a new screenshot when no
    # overlays were dismissed (the overlay pipeline already emits
    # one after every successful dismiss).
    if ctx.overlay_count == 0:
        log.info("No overlays dismissed — capturing final page state")
        await session.capture_current_cookies()
        event_str, _, ctx.storage = await sse_helpers.take_screenshot_event(session)
        yield event_str
    else:
        await session.capture_current_cookies()
        ctx.storage = await session.capture_storage()

    if page and ctx.overlay_result.failed:
        if ctx.consent_details:
            log.warn(
                "Overlay click failed but consent data preserved — continuing analysis",
                {
                    "categories": len(ctx.consent_details.categories),
                    "partners": len(ctx.consent_details.partners),
                },
            )
        else:
            log.error(
                "Overlay dismissal failed, aborting analysis",
                {"reason": ctx.overlay_result.failure_message},
            )
            yield sse_helpers.format_sse_event(
                "pageError",
                {
                    "type": "overlay-blocked",
                    "message": ctx.overlay_result.failure_message,
                    "isOverlayBlocked": True,
                },
            )
            yield sse_helpers.format_progress_event(
                "overlay-blocked",
                "Could not dismiss page overlay!",
                100,
            )
            ctx.aborted = True
            return

    # Post-overlay stabilisation — brief network-idle race
    # for deferred tracking scripts to arrive.
    if ctx.overlay_count > 0:
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


async def _run_phase_5_analysis(ctx: _StreamContext) -> AsyncGenerator[str]:
    """Phase 5: Stage 2 screenshot refresher + AI analysis.

    Starts a fresh screenshot refresher, runs the analysis
    pipeline, and drains any remaining refresh events.
    """
    session = ctx.session

    # ── Stage 2 screenshot refresher ────────────────
    remaining_refreshes = _MAX_SCREENSHOT_REFRESHES
    current_hash = ""

    if remaining_refreshes > 0:
        try:
            png = await session.take_screenshot(full_page=False)
            current_hash = hashlib.md5(png).hexdigest()
            optimized = browser_session.BrowserSession.optimize_screenshot_bytes(png)
            yield sse_helpers.format_screenshot_update_event(optimized)
            remaining_refreshes -= 1
            log.info("Immediate pre-analysis screenshot refresh emitted")
        except Exception:
            log.debug("Pre-analysis screenshot refresh failed — skipping")

    refresh_queue: asyncio.Queue[str] = asyncio.Queue()
    ctx.refresh_queue = refresh_queue
    if remaining_refreshes > 0:
        ctx.refresher_task = asyncio.create_task(
            _screenshot_refresher(
                session,
                refresh_queue,
                current_hash,
                remaining=remaining_refreshes,
            ),
        )
        log.debug(
            "Stage 2 screenshot refresher started",
            {"remaining": remaining_refreshes},
        )
    else:
        ctx.refresher_task = None

    # ── AI Analysis ────────────────────────────────────
    log.subsection("Phase 5: AI Analysis")

    async for event in analysis_pipeline.run_ai_analysis(
        session,
        ctx.storage,
        ctx.url,
        ctx.consent_details,
        ctx.overlay_count,
        ctx.pre_consent_stats,
    ):
        yield event
        for refresh_event in _drain_queue(refresh_queue):
            yield refresh_event

    # Stop the refresher now that analysis is done.
    if ctx.refresher_task and not ctx.refresher_task.done():
        ctx.refresher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ctx.refresher_task
    for refresh_event in _drain_queue(refresh_queue):
        yield refresh_event


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
