"""
Streaming URL analysis endpoint with progress updates.
Provides Server-Sent Events (SSE) endpoint for real-time progress during
page loading, consent handling, and tracking analysis.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator
from urllib.parse import urlparse

from src.routes.analyze_helpers import (
    OverlayHandlingResult,
    format_progress_event,
    format_sse_event,
    handle_overlays,
    serialize_consent_details,
    serialize_score_breakdown,
    to_camel_case_dict,
)
from src.services.analysis import run_tracking_analysis
from src.services.browser_session import BrowserSession
from src.services.device_configs import DEVICE_CONFIGS
from src.services.openai_client import get_deployment_name, validate_openai_config
from src.services.script_analysis import analyze_scripts
from src.utils.errors import get_error_message
from src.utils.logger import create_logger, start_log_file
from src.utils.url import extract_domain

log = create_logger("Analyze")


async def analyze_url_stream(url: str, device: str = "ipad") -> AsyncGenerator[str, None]:
    """
    Analyze tracking on a URL with streaming progress via SSE.

    Opens a browser, navigates to the URL, detects and handles cookie
    consent banners, captures tracking data, and runs AI analysis. Progress
    is streamed via Server-Sent Events (SSE).

    Each call creates its own isolated BrowserSession, enabling concurrent
    analyses without interference.
    """
    # Validate OpenAI configuration
    config_error = validate_openai_config()
    if config_error:
        yield format_sse_event("error", {"error": config_error})
        return

    # Validate device type
    valid_devices = list(DEVICE_CONFIGS.keys())
    device_type = device if device in valid_devices else "ipad"

    if not url:
        yield format_sse_event("error", {"error": "URL is required"})
        return

    # Create isolated browser session
    session = BrowserSession()

    # Start file logging
    domain = extract_domain(url)
    start_log_file(domain)

    log.section(f"Analyzing: {url}")
    log.info("Request received", {"url": url, "device": device_type, "model": get_deployment_name()})
    log.start_timer("total-analysis")

    try:
        # ====================================================================
        # Phase 1: Browser Setup and Navigation
        # ====================================================================
        log.subsection("Phase 1: Browser Setup")
        yield format_progress_event("init", "Warming up...", 5)

        session.clear_tracking_data()
        session.set_current_page_url(url)

        log.start_timer("browser-launch")
        yield format_progress_event("browser", "Launching browser...", 8)
        await session.launch_browser(device_type)
        log.end_timer("browser-launch", "Browser launched")

        hostname = urlparse(url).hostname or url
        log.start_timer("navigation")
        log.info("Navigating to page", {"hostname": hostname})
        yield format_progress_event("navigate", f"Connecting to {hostname}...", 12)

        nav_result = await session.navigate_to(url, "domcontentloaded", 30000)
        log.end_timer("navigation", "Initial navigation complete")
        log.info("Navigation result", {"success": nav_result.success, "statusCode": nav_result.status_code})

        if not nav_result.success:
            error_type = "access-denied" if nav_result.is_access_denied else "server-error"
            log.error("Navigation failed", {"errorType": error_type, "statusCode": nav_result.status_code})
            yield format_sse_event("pageError", {
                "type": error_type,
                "statusCode": nav_result.status_code,
                "message": nav_result.error_message,
                "isAccessDenied": nav_result.is_access_denied,
            })
            yield format_progress_event("error", nav_result.error_message or "Failed to load page", 100)
            return

        # ====================================================================
        # Phase 2: Wait for Page Load and Check Access
        # ====================================================================
        log.subsection("Phase 2: Page Load & Access Check")
        log.start_timer("network-idle")
        yield format_progress_event("wait-network", f"Loading {hostname}...", 18)

        network_idle = await session.wait_for_network_idle(20000)
        log.end_timer("network-idle", "Network idle wait complete")

        if not network_idle:
            log.warn("Network still active (normal for ad-heavy sites), continuing...")
            yield format_progress_event("wait-continue", "Page loaded, waiting for ads to render...", 25)
            await session.wait_for_timeout(3000)
        else:
            log.success("Network became idle")
            yield format_progress_event("wait-done", "Page fully loaded", 28)

        yield format_progress_event("wait-ads", "Waiting for dynamic content...", 28)
        await session.wait_for_timeout(2000)

        # Check for access denied
        log.start_timer("access-check")
        access_check = await session.check_for_access_denied()
        log.end_timer("access-check", "Access check complete")

        if access_check.denied:
            log.error("Access denied detected", {"reason": access_check.reason})
            screenshot = await session.take_screenshot(full_page=False)
            optimized = await session.take_optimized_screenshot(full_page=False)

            yield format_sse_event("screenshot", {
                "screenshot": optimized,
                "cookies": [to_camel_case_dict(c) for c in session.get_tracked_cookies()],
                "scripts": [to_camel_case_dict(s) for s in session.get_tracked_scripts()],
                "networkRequests": [to_camel_case_dict(r) for r in session.get_tracked_network_requests()],
                "localStorage": [],
                "sessionStorage": [],
            })
            yield format_sse_event("pageError", {
                "type": "access-denied",
                "statusCode": nav_result.status_code,
                "message": "Access denied - this site has bot protection that blocked our request",
                "isAccessDenied": True,
                "reason": access_check.reason,
            })
            yield format_progress_event("blocked", "Site blocked access", 100)
            return

        # ====================================================================
        # Phase 3: Initial Data Capture
        # ====================================================================
        log.subsection("Phase 3: Initial Data Capture")
        log.start_timer("initial-capture")

        yield format_progress_event("cookies", "Capturing cookies...", 32)
        await session.capture_current_cookies()

        yield format_progress_event("storage", "Capturing storage data...", 35)
        storage = await session.capture_storage()

        yield format_progress_event("overlay-wait", "Waiting for page overlays...", 37)
        await session.wait_for_timeout(2000)

        yield format_progress_event("screenshot", "Taking screenshot...", 38)
        screenshot = await session.take_screenshot(full_page=False)
        optimized_screenshot = await session.take_optimized_screenshot(full_page=False)

        # Send screenshot to client immediately
        yield format_sse_event("screenshot", {
            "screenshot": optimized_screenshot,
            "cookies": [to_camel_case_dict(c) for c in session.get_tracked_cookies()],
            "scripts": [to_camel_case_dict(s) for s in session.get_tracked_scripts()],
            "networkRequests": [to_camel_case_dict(r) for r in session.get_tracked_network_requests()],
            "localStorage": [to_camel_case_dict(i) for i in storage["local_storage"]],
            "sessionStorage": [to_camel_case_dict(i) for i in storage["session_storage"]],
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

        yield format_progress_event(
            "captured",
            f"Found {cookie_count} cookies, {script_count} scripts, {request_count} requests",
            42,
        )

        # ====================================================================
        # Phase 4: Overlay Detection and Handling
        # ====================================================================
        log.subsection("Phase 4: Overlay Detection & Handling")
        log.start_timer("overlay-handling")
        yield format_progress_event("overlay-detect", "Checking for page overlays...", 45)

        page = session.get_page()
        consent_details = None
        overlay_count = 0

        if page:
            overlay_result = OverlayHandlingResult()
            async for event_str in handle_overlays(session, page, screenshot, overlay_result):
                yield event_str
            consent_details = overlay_result.consent_details
            overlay_count = overlay_result.overlay_count
            storage = overlay_result.final_storage

        log.end_timer("overlay-handling", "Overlay handling complete")
        log.info("Overlay handling result", {"overlaysFound": overlay_count, "hasConsentDetails": consent_details is not None})

        # ====================================================================
        # Phase 5: AI Analysis
        # ====================================================================
        log.subsection("Phase 5: AI Analysis")
        yield format_progress_event("analysis-prep", "Preparing tracking data for analysis...", 75)

        final_cookies = session.get_tracked_cookies()
        final_scripts = session.get_tracked_scripts()
        final_requests = session.get_tracked_network_requests()

        log.info("Final data stats", {
            "cookies": len(final_cookies),
            "scripts": len(final_scripts),
            "requests": len(final_requests),
        })
        yield format_progress_event(
            "analysis-start",
            f"Found {len(final_cookies)} cookies, {len(final_scripts)} scripts, {len(final_requests)} requests",
            76,
        )

        log.start_timer("ai-analysis")

        # Script analysis
        log.start_timer("script-analysis")

        script_progress_queue: asyncio.Queue[str | None] = asyncio.Queue()

        def script_progress(phase: str, current: int, total: int, detail: str) -> None:
            """Push progress events onto an async queue for yielding."""
            log.info(f"Script analysis progress: {phase} {current}/{total} - {detail}")
            if phase == "matching":
                if current == 0:
                    script_progress_queue.put_nowait(
                        format_progress_event("script-matching", detail or "Grouping and identifying scripts...", 77)
                    )
            elif phase == "fetching":
                progress = 77 + int((current / max(total, 1)) * 2)
                script_progress_queue.put_nowait(
                    format_progress_event("script-fetching", detail or f"Fetching script {current}/{total}...", progress)
                )
            elif phase == "analyzing":
                if total == 0:
                    script_progress_queue.put_nowait(
                        format_progress_event("script-analysis", detail or "All scripts identified", 82)
                    )
                else:
                    progress = 79 + int((current / total) * 4)
                    script_progress_queue.put_nowait(
                        format_progress_event("script-analysis", detail or f"Analyzed {current}/{total} scripts...", progress)
                    )

        async def run_script_analysis() -> Any:
            """Run script analysis and signal the queue on completion."""
            try:
                result = await analyze_scripts(final_scripts, script_progress)
                return result
            finally:
                script_progress_queue.put_nowait(None)  # always signal completion

        script_task = asyncio.create_task(run_script_analysis())
        while True:
            event = await script_progress_queue.get()
            if event is None:
                break
            yield event

        script_analysis_result = await script_task
        log.end_timer("script-analysis", f"Script analysis complete ({len(script_analysis_result.scripts)} scripts, {len(script_analysis_result.groups)} groups)")

        yield format_progress_event("script-analysis", "Script analysis complete", 83)

        # Tracking analysis
        log.start_timer("tracking-analysis")

        analysis_progress_queue: asyncio.Queue[str | None] = asyncio.Queue()

        def analysis_progress(phase: str, detail: str) -> None:
            """Push AI analysis progress events onto an async queue."""
            log.info(f"Analysis: {phase} - {detail}")
            if phase == "preparing":
                analysis_progress_queue.put_nowait(
                    format_progress_event("ai-preparing", detail or "Preparing data for AI analysis...", 84)
                )
            elif phase == "analyzing":
                analysis_progress_queue.put_nowait(
                    format_progress_event("ai-analyzing", detail or "Generating privacy report...", 88)
                )
            elif phase == "scoring":
                analysis_progress_queue.put_nowait(
                    format_progress_event("ai-scoring", detail or "Calculating privacy score...", 94)
                )
            elif phase == "summarizing":
                analysis_progress_queue.put_nowait(
                    format_progress_event("ai-summarizing", detail or "Generating summary findings...", 97)
                )

        async def run_analysis() -> Any:
            """Run tracking analysis and signal the queue on completion."""
            try:
                result = await run_tracking_analysis(
                    final_cookies,
                    storage["local_storage"],
                    storage["session_storage"],
                    final_requests,
                    final_scripts,
                    url,
                    consent_details,
                    analysis_progress,
                )
                return result
            finally:
                analysis_progress_queue.put_nowait(None)  # always signal completion

        analysis_task = asyncio.create_task(run_analysis())
        while True:
            event = await analysis_progress_queue.get()
            if event is None:
                break
            yield event

        analysis_result = await analysis_task
        log.end_timer("tracking-analysis", "Tracking analysis complete")

        log.end_timer("ai-analysis", "All AI analysis complete")

        if analysis_result.success:
            log.success("Analysis succeeded", {
                "privacyScore": analysis_result.privacy_score,
                "analysisLength": len(analysis_result.analysis or ""),
            })
        else:
            log.error("Analysis failed", {"error": analysis_result.error})

        # ====================================================================
        # Phase 6: Complete
        # ====================================================================
        total_time = log.end_timer("total-analysis", "Analysis complete")
        log.success("Investigation complete!", {
            "totalTime": f"{(total_time / 1000):.2f}s",
            "overlaysDismissed": overlay_count,
            "privacyScore": analysis_result.privacy_score,
        })

        yield format_progress_event("complete", "Investigation complete!", 100)

        # Build consent details for response
        consent_details_dict = serialize_consent_details(consent_details) if consent_details else None

        # Build score breakdown dict
        score_breakdown_dict = (
            serialize_score_breakdown(analysis_result.score_breakdown)
            if analysis_result.score_breakdown
            else None
        )

        yield format_sse_event("complete", {
            "success": True,
            "message": (
                "Tracking analyzed after dismissing overlays"
                if overlay_count > 0
                else "Tracking analyzed"
            ),
            "analysis": analysis_result.analysis if analysis_result.success else None,
            "summaryFindings": (
                [{"type": f.type, "text": f.text} for f in analysis_result.summary_findings]
                if analysis_result.success
                else None
            ),
            "privacyScore": analysis_result.privacy_score if analysis_result.success else None,
            "privacySummary": analysis_result.privacy_summary if analysis_result.success else None,
            "scoreBreakdown": score_breakdown_dict if analysis_result.success else None,
            "analysisSummary": (
                {
                    "analyzedUrl": analysis_result.summary.analyzed_url,
                    "totalCookies": analysis_result.summary.total_cookies,
                    "totalScripts": analysis_result.summary.total_scripts,
                    "totalNetworkRequests": analysis_result.summary.total_network_requests,
                    "localStorageItems": analysis_result.summary.local_storage_items,
                    "sessionStorageItems": analysis_result.summary.session_storage_items,
                    "thirdPartyDomains": analysis_result.summary.third_party_domains,
                    "domainBreakdown": [to_camel_case_dict(d) for d in analysis_result.summary.domain_breakdown],
                    "localStorage": analysis_result.summary.local_storage,
                    "sessionStorage": analysis_result.summary.session_storage,
                }
                if analysis_result.summary
                else None
            ),
            "analysisError": analysis_result.error if not analysis_result.success else None,
            "consentDetails": consent_details_dict,
            "scripts": [to_camel_case_dict(s) for s in script_analysis_result.scripts],
            "scriptGroups": [to_camel_case_dict(g) for g in script_analysis_result.groups],
        })

    except Exception as error:
        log.error("Analysis failed with exception", {"error": get_error_message(error)})
        yield format_sse_event("error", {"error": get_error_message(error)})
    finally:
        log.debug("Cleaning up browser resources...")
        try:
            await session.close()
        except Exception as err:
            log.warn("Error during browser cleanup", {"error": get_error_message(err)})
        log.debug("Browser cleanup complete")
