"""
Streaming URL analysis endpoint with progress updates.
Provides Server-Sent Events (SSE) endpoint for real-time progress during
page loading, consent handling, and tracking analysis.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, cast
from urllib import parse

from src.routes import analyze_helpers
from src.agents import config as agent_config
from src.services import (
    analysis,
    browser_session,
    device_configs,
    script_analysis,
)
from src.types import browser
from src.utils import errors, logger
from src.utils import url as url_mod

log = logger.create_logger("Analyze")


async def analyze_url_stream(url: str, device: str = "ipad") -> AsyncGenerator[str, None]:
    """
    Analyze tracking on a URL with streaming progress via SSE.

    Opens a browser, navigates to the URL, detects and handles cookie
    consent banners, captures tracking data, and runs AI analysis. Progress
    is streamed via Server-Sent Events (SSE).

    Each call creates its own isolated BrowserSession, enabling concurrent
    analyses without interference.
    """
    # Validate LLM configuration
    config_error = agent_config.validate_llm_config()
    if config_error:
        yield analyze_helpers.format_sse_event("error", {"error": config_error})
        return

    # Validate device type
    valid_devices = list(device_configs.DEVICE_CONFIGS.keys())
    device_type = cast(browser.DeviceType, device if device in valid_devices else "ipad")

    if not url:
        yield analyze_helpers.format_sse_event("error", {"error": "URL is required"})
        return

    # Create isolated browser session
    session = browser_session.BrowserSession()

    # Start file logging
    domain = url_mod.extract_domain(url)
    logger.start_log_file(domain)

    log.section(f"Analyzing: {url}")
    log.info("Request received", {"url": url, "device": device_type})
    log.start_timer("total-analysis")

    try:
        # ====================================================================
        # Phase 1: Browser Setup and Navigation
        # ====================================================================
        log.subsection("Phase 1: Browser Setup")
        yield analyze_helpers.format_progress_event("init", "Warming up...", 5)

        session.clear_tracking_data()
        session.set_current_page_url(url)

        log.start_timer("browser-launch")
        yield analyze_helpers.format_progress_event("browser", "Launching browser...", 8)
        await session.launch_browser(device_type)
        log.end_timer("browser-launch", "Browser launched")

        hostname = parse.urlparse(url).hostname or url
        log.start_timer("navigation")
        log.info("Navigating to page", {"hostname": hostname})
        yield analyze_helpers.format_progress_event("navigate", f"Connecting to {hostname}...", 12)

        nav_result = await session.navigate_to(url, "domcontentloaded", 30000)
        log.end_timer("navigation", "Initial navigation complete")
        log.info("Navigation result", {"success": nav_result.success, "statusCode": nav_result.status_code})

        if not nav_result.success:
            error_type = "access-denied" if nav_result.is_access_denied else "server-error"
            log.error("Navigation failed", {"errorType": error_type, "statusCode": nav_result.status_code})
            yield analyze_helpers.format_sse_event("pageError", {
                "type": error_type,
                "statusCode": nav_result.status_code,
                "message": nav_result.error_message,
                "isAccessDenied": nav_result.is_access_denied,
            })
            yield analyze_helpers.format_progress_event("error", nav_result.error_message or "Failed to load page", 100)
            return

        # ====================================================================
        # Phase 2: Wait for Page Load and Check Access
        # ====================================================================
        log.subsection("Phase 2: Page Load & Access Check")
        log.start_timer("network-idle")
        yield analyze_helpers.format_progress_event("wait-network", f"Loading {hostname}...", 18)

        network_idle = await session.wait_for_network_idle(20000)
        log.end_timer("network-idle", "Network idle wait complete")

        if not network_idle:
            log.warn("Network still active (normal for ad-heavy sites), continuing...")
            yield analyze_helpers.format_progress_event("wait-continue", "Page loaded, waiting for ads to render...", 25)
            await session.wait_for_timeout(3000)
        else:
            log.success("Network became idle")
            yield analyze_helpers.format_progress_event("wait-done", "Page fully loaded", 28)

        yield analyze_helpers.format_progress_event("wait-ads", "Waiting for dynamic content...", 28)
        await session.wait_for_timeout(2000)

        # Check for access denied
        log.start_timer("access-check")
        access_check = await session.check_for_access_denied()
        log.end_timer("access-check", "Access check complete")

        if access_check.denied:
            log.error("Access denied detected", {"reason": access_check.reason})
            screenshot = await session.take_screenshot(full_page=False)
            optimized = browser_session.BrowserSession.optimize_screenshot_bytes(screenshot)

            yield analyze_helpers.format_sse_event("screenshot", {
                "screenshot": optimized,
                "cookies": [analyze_helpers.to_camel_case_dict(c) for c in session.get_tracked_cookies()],
                "scripts": [analyze_helpers.to_camel_case_dict(s) for s in session.get_tracked_scripts()],
                "networkRequests": [analyze_helpers.to_camel_case_dict(r) for r in session.get_tracked_network_requests()],
                "localStorage": [],
                "sessionStorage": [],
            })
            yield analyze_helpers.format_sse_event("pageError", {
                "type": "access-denied",
                "statusCode": nav_result.status_code,
                "message": "Access denied - this site has bot protection that blocked our request",
                "isAccessDenied": True,
                "reason": access_check.reason,
            })
            yield analyze_helpers.format_progress_event("blocked", "Site blocked access", 100)
            return

        # ====================================================================
        # Phase 3: Initial Data Capture
        # ====================================================================
        log.subsection("Phase 3: Initial Data Capture")
        log.start_timer("initial-capture")

        yield analyze_helpers.format_progress_event("cookies", "Capturing cookies...", 32)
        await session.capture_current_cookies()

        yield analyze_helpers.format_progress_event("storage", "Capturing storage data...", 35)
        storage = await session.capture_storage()

        yield analyze_helpers.format_progress_event("overlay-wait", "Waiting for page overlays...", 37)
        await session.wait_for_timeout(2000)

        yield analyze_helpers.format_progress_event("screenshot", "Taking screenshot...", 38)
        screenshot = await session.take_screenshot(full_page=False)
        optimized_screenshot = browser_session.BrowserSession.optimize_screenshot_bytes(screenshot)

        # Send screenshot to client immediately
        yield analyze_helpers.format_sse_event("screenshot", {
            "screenshot": optimized_screenshot,
            "cookies": [analyze_helpers.to_camel_case_dict(c) for c in session.get_tracked_cookies()],
            "scripts": [analyze_helpers.to_camel_case_dict(s) for s in session.get_tracked_scripts()],
            "networkRequests": [analyze_helpers.to_camel_case_dict(r) for r in session.get_tracked_network_requests()],
            "localStorage": [analyze_helpers.to_camel_case_dict(i) for i in storage["local_storage"]],
            "sessionStorage": [analyze_helpers.to_camel_case_dict(i) for i in storage["session_storage"]],
        })

        cookie_count = len(session.get_tracked_cookies())
        script_count = len(session.get_tracked_scripts())
        request_count = len(session.get_tracked_network_requests())

        log.end_timer("initial-capture", "Initial data captured")
        log.info("Initial capture stats", {
            "cookies": cookie_count,
            "scripts": script_count,
            "requests": request_count,
            "localStorage": len(storage["local_storage"]),
            "sessionStorage": len(storage["session_storage"]),
        })

        yield analyze_helpers.format_progress_event(
            "captured",
            f"Found {cookie_count} cookies, {script_count} scripts, {request_count} requests",
            42,
        )

        # ====================================================================
        # Phase 4: Overlay Detection and Handling
        # ====================================================================
        log.subsection("Phase 4: Overlay Detection & Handling")
        log.start_timer("overlay-handling")
        yield analyze_helpers.format_progress_event("overlay-detect", "Checking for page overlays...", 45)

        page = session.get_page()
        consent_details = None
        overlay_count = 0

        if page:
            overlay_result = analyze_helpers.OverlayHandlingResult()
            async for event_str in analyze_helpers.handle_overlays(session, page, screenshot, overlay_result):
                yield event_str
            consent_details = overlay_result.consent_details
            overlay_count = overlay_result.overlay_count
            storage = overlay_result.final_storage

        log.end_timer("overlay-handling", "Overlay handling complete")
        log.info("Overlay handling result", {"overlaysFound": overlay_count, "hasConsentDetails": consent_details is not None})

        # Capture a fresh screenshot after overlay handling.
        yield analyze_helpers.format_progress_event("post-overlay-screenshot", "Capturing final page state...", 72)
        screenshot = await session.take_screenshot(full_page=False)
        optimized_screenshot = browser_session.BrowserSession.optimize_screenshot_bytes(screenshot)
        await session.capture_current_cookies()
        storage = await session.capture_storage()

        yield analyze_helpers.format_sse_event("screenshot", {
            "screenshot": optimized_screenshot,
            "cookies": [analyze_helpers.to_camel_case_dict(c) for c in session.get_tracked_cookies()],
            "scripts": [analyze_helpers.to_camel_case_dict(s) for s in session.get_tracked_scripts()],
            "networkRequests": [analyze_helpers.to_camel_case_dict(r) for r in session.get_tracked_network_requests()],
            "localStorage": [analyze_helpers.to_camel_case_dict(i) for i in storage["local_storage"]],
            "sessionStorage": [analyze_helpers.to_camel_case_dict(i) for i in storage["session_storage"]],
        })

        # Abort if an overlay could not be dismissed — the page is blocked.
        if page and overlay_result.failed:
            log.error("Overlay dismissal failed, aborting analysis", {"reason": overlay_result.failure_message})
            yield analyze_helpers.format_sse_event("pageError", {
                "type": "overlay-blocked",
                "message": overlay_result.failure_message,
                "isOverlayBlocked": True,
            })
            yield analyze_helpers.format_progress_event("overlay-blocked", "Could not dismiss page overlay", 100)
            return

        # ====================================================================
        # Phase 5: AI Analysis
        # ====================================================================
        log.subsection("Phase 5: AI Analysis")
        yield analyze_helpers.format_progress_event("analysis-prep", "Preparing tracking data for analysis...", 75)

        final_cookies = session.get_tracked_cookies()
        final_scripts = session.get_tracked_scripts()
        final_requests = session.get_tracked_network_requests()

        log.info("Final data stats", {
            "cookies": len(final_cookies),
            "scripts": len(final_scripts),
            "requests": len(final_requests),
        })
        yield analyze_helpers.format_progress_event(
            "analysis-start",
            f"Found {len(final_cookies)} cookies, {len(final_scripts)} scripts, {len(final_requests)} requests",
            76,
        )

        log.start_timer("ai-analysis")

        # ---- Shared progress queue for concurrent tasks ----
        progress_queue: asyncio.Queue[str | None] = asyncio.Queue()
        _tasks_remaining = 2  # script analysis + streaming analysis

        # ---- Script analysis (runs concurrently) ----
        log.start_timer("script-analysis")

        def script_progress(phase: str, current: int, total: int, detail: str) -> None:
            """Push progress events onto the async queue."""
            log.info(f"Script analysis progress: {phase} {current}/{total} - {detail}")
            if phase == "matching":
                if current == 0:
                    progress_queue.put_nowait(
                        analyze_helpers.format_progress_event("script-matching", detail or "Grouping and identifying scripts...", 77)
                    )
            elif phase == "fetching":
                progress = 77 + int((current / max(total, 1)) * 2)
                progress_queue.put_nowait(
                    analyze_helpers.format_progress_event("script-fetching", detail or f"Fetching script {current}/{total}...", progress)
                )
            elif phase == "analyzing":
                if total == 0:
                    progress_queue.put_nowait(
                        analyze_helpers.format_progress_event("script-analysis", detail or "All scripts identified", 82)
                    )
                else:
                    progress = 79 + int((current / total) * 11)
                    progress_queue.put_nowait(
                        analyze_helpers.format_progress_event("script-analysis", detail or f"Analyzed {current}/{total} scripts...", progress)
                    )

        async def run_script_analysis() -> Any:
            """Run script analysis and signal the queue."""
            try:
                result = await script_analysis.analyze_scripts(final_scripts, script_progress)
                log.end_timer("script-analysis", f"Script analysis complete ({len(result.scripts)} scripts, {len(result.groups)} groups)")
                return result
            finally:
                progress_queue.put_nowait(None)

        # ---- Streaming tracking analysis (runs concurrently) ----
        log.start_timer("tracking-analysis")
        analysis_chunks: list[str] = []

        async def run_streaming_analysis() -> None:
            """Stream tracking analysis and push chunks + progress to queue."""
            try:
                async for chunk in analysis.stream_tracking_analysis(
                    final_cookies,
                    storage["local_storage"],
                    storage["session_storage"],
                    final_requests,
                    final_scripts,
                    url,
                    consent_details,
                ):
                    analysis_chunks.append(chunk)
                    progress_queue.put_nowait(
                        analyze_helpers.format_sse_event("analysis-chunk", {"text": chunk})
                    )
            finally:
                progress_queue.put_nowait(None)

        # Launch both concurrently
        script_task = asyncio.create_task(run_script_analysis())
        analysis_stream_task = asyncio.create_task(run_streaming_analysis())

        # Drain progress events until both signal completion
        finished = 0
        while finished < _tasks_remaining:
            event = await progress_queue.get()
            if event is None:
                finished += 1
                continue
            yield event

        await script_task
        await analysis_stream_task
        script_analysis_result = script_task.result()

        log.end_timer("tracking-analysis", "Tracking analysis complete")

        # ---- Post-streaming: scoring + summary findings ----
        full_analysis_text = "".join(analysis_chunks)
        log.info("Analysis streamed", {"length": len(full_analysis_text)})

        yield analyze_helpers.format_progress_event("ai-scoring", "Calculating privacy score...", 94)
        from src.services import privacy_score as privacy_score_mod
        from src.utils import tracking_summary as tracking_summary_mod

        tracking_summary = tracking_summary_mod.build_tracking_summary(
            final_cookies, final_scripts, final_requests,
            storage["local_storage"], storage["session_storage"], url,
        )

        score_breakdown = privacy_score_mod.calculate_privacy_score(
            final_cookies, final_scripts, final_requests,
            storage["local_storage"], storage["session_storage"],
            url, consent_details,
        )

        yield analyze_helpers.format_progress_event("ai-summarizing", "Generating summary findings...", 97)
        from src.agents import get_summary_findings_agent
        summary_agent = get_summary_findings_agent()
        summary_findings = await summary_agent.summarise(full_analysis_text)

        log.end_timer("ai-analysis", "All AI analysis complete")

        analysis_success = bool(full_analysis_text)
        privacy_score = score_breakdown.total_score
        privacy_summary = score_breakdown.summary

        if analysis_success:
            log.success("Analysis succeeded", {
                "privacyScore": privacy_score,
                "analysisLength": len(full_analysis_text),
            })
        else:
            log.error("Analysis produced no output")

        # ====================================================================
        # Phase 6: Complete
        # ====================================================================
        total_time = log.end_timer("total-analysis", "Analysis complete")
        log.success("Investigation complete!", {
            "totalTime": f"{(total_time / 1000):.2f}s",
            "overlaysDismissed": overlay_count,
            "privacyScore": privacy_score,
        })

        yield analyze_helpers.format_progress_event("complete", "Investigation complete!", 100)

        # Build consent details for response
        consent_details_dict = analyze_helpers.serialize_consent_details(consent_details) if consent_details else None

        # Build score breakdown dict
        score_breakdown_dict = (
            analyze_helpers.serialize_score_breakdown(score_breakdown)
            if score_breakdown
            else None
        )

        yield analyze_helpers.format_sse_event("complete", {
            "success": True,
            "message": (
                "Tracking analyzed after dismissing overlays"
                if overlay_count > 0
                else "Tracking analyzed"
            ),
            "analysis": full_analysis_text if analysis_success else None,
            "summaryFindings": (
                [{"type": f.type, "text": f.text} for f in summary_findings]
                if analysis_success
                else None
            ),
            "privacyScore": privacy_score if analysis_success else None,
            "privacySummary": privacy_summary if analysis_success else None,
            "scoreBreakdown": score_breakdown_dict if analysis_success else None,
            "analysisSummary": (
                {
                    "analyzedUrl": tracking_summary.analyzed_url,
                    "totalCookies": tracking_summary.total_cookies,
                    "totalScripts": tracking_summary.total_scripts,
                    "totalNetworkRequests": tracking_summary.total_network_requests,
                    "localStorageItems": tracking_summary.local_storage_items,
                    "sessionStorageItems": tracking_summary.session_storage_items,
                    "thirdPartyDomains": tracking_summary.third_party_domains,
                    "domainBreakdown": [analyze_helpers.to_camel_case_dict(d) for d in tracking_summary.domain_breakdown],
                    "localStorage": tracking_summary.local_storage,
                    "sessionStorage": tracking_summary.session_storage,
                }
                if tracking_summary
                else None
            ),
            "analysisError": None if analysis_success else "Analysis produced no output",
            "consentDetails": consent_details_dict,
            "scripts": [analyze_helpers.to_camel_case_dict(s) for s in script_analysis_result.scripts],
            "scriptGroups": [analyze_helpers.to_camel_case_dict(g) for g in script_analysis_result.groups],
        })

    except Exception as error:
        log.error("Analysis failed with exception", {"error": errors.get_error_message(error)})
        yield analyze_helpers.format_sse_event("error", {"error": errors.get_error_message(error)})
    finally:
        log.debug("Cleaning up browser resources...")
        try:
            await session.close()
        except Exception as err:
            log.warn("Error during browser cleanup", {"error": errors.get_error_message(err)})
        log.debug("Browser cleanup complete")
        logger.end_log_file()
