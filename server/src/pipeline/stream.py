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
import dataclasses
import os
import pathlib
import tomllib
from collections.abc import AsyncGenerator, Callable
from typing import Any, cast
from urllib import parse

from src.agents import config
from src.analysis import cookie_decoders, tc_string, tc_validation, tcf_lookup, tracking_summary, vendor_lookup
from src.browser import device_configs
from src.browser import manager as browser_manager
from src.browser import session as browser_session
from src.consent import overlay_cache, platform_detection
from src.models import analysis, browser, consent, tracking_data
from src.pipeline import analysis_pipeline, browser_phases, overlay_pipeline, sse_helpers
from src.utils import cache, errors, logger, usage_tracking
from src.utils import url as url_mod

log = logger.create_logger("Analyze")


def _read_version() -> str:
    """Read the server version from ``pyproject.toml``."""
    try:
        pyproject = pathlib.Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except Exception:
        return "unknown"


_SERVER_VERSION = _read_version()


# ── Consent-string discovery helpers ─────────────────────────


@dataclasses.dataclass(frozen=True, slots=True)
class _ConsentStringTiers:
    """Callables for each tier of a consent-string discovery cascade."""

    cookie_label: str
    find_in_cookies: Callable[..., Any]
    find_in_storage: Callable[..., Any]
    find_by_profile: Callable[..., Any]
    find_in_json_storage: Callable[..., Any]
    scan: Callable[..., Any]
    scan_json: Callable[..., Any]


def _discover_consent_string(
    tiers: _ConsentStringTiers,
    tracked_cookies: list[Any],
    local_storage: list[Any],
    tc_sources: dict[str, Any],
) -> tuple[str, str] | None:
    """Run the 5-tier consent-string discovery cascade.

    Both TC and AC strings are located using an identical
    progression from deterministic lookups to heuristic scans.
    This function centralises that logic so callers differ only
    in the tier callables they provide.

    Args:
        tiers: Tier callables and the cookie-source label.
        tracked_cookies: Captured cookies from the session.
        local_storage: Captured ``localStorage`` entries.
        tc_sources: CMP-specific source hints (may be empty).

    Returns:
        A ``(source_label, raw_value)`` pair, or ``None``.
    """
    # Tier 1 — named lookups
    raw = tiers.find_in_cookies(tracked_cookies)
    if raw:
        return (tiers.cookie_label, raw)
    storage = tiers.find_in_storage(local_storage)
    if storage:
        return (f"localStorage[{storage[0]}]", storage[1])

    # Tier 2 — CMP-aware lookups
    if tc_sources:
        result: tuple[str, str] | None = tiers.find_by_profile(
            tracked_cookies,
            local_storage,
            tc_sources,
        )
        if result:
            return result

    # Tier 3 — JSON-wrapped storage values
    json_result: tuple[str, str] | None = tiers.find_in_json_storage(local_storage)
    if json_result:
        return json_result

    # Tier 4 — heuristic scan
    scan_result: tuple[str, str] | None = tiers.scan(tracked_cookies, local_storage)
    if scan_result:
        return scan_result

    # Tier 5 — JSON heuristic scan
    final: tuple[str, str] | None = tiers.scan_json(local_storage)
    return final


_AC_TIERS = _ConsentStringTiers(
    cookie_label="addtl_consent cookie",
    find_in_cookies=tc_string.find_ac_string_in_cookies,
    find_in_storage=tc_string.find_ac_string_in_storage,
    find_by_profile=tc_string.find_ac_string_by_profile,
    find_in_json_storage=tc_string.find_ac_string_in_json_storage,
    scan=tc_string.scan_for_ac_string,
    scan_json=tc_string.scan_json_for_ac_string,
)

_TC_TIERS = _ConsentStringTiers(
    cookie_label="euconsent-v2 cookie",
    find_in_cookies=tc_string.find_tc_string_in_cookies,
    find_in_storage=tc_string.find_tc_string_in_storage,
    find_by_profile=tc_string.find_tc_string_by_profile,
    find_in_json_storage=tc_string.find_tc_string_in_json_storage,
    scan=tc_string.scan_for_tc_string,
    scan_json=tc_string.scan_json_for_tc_string,
)


# Maximum wall-clock time (seconds) for a single analysis run.
# Prevents runaway sessions from holding browser resources
# indefinitely.  Individual phases may finish faster; this is
# the outer safety net.
STREAM_TIMEOUT_SECONDS = 600  # 10 minutes

# Maximum number of concurrent browser sessions.  Each session
# runs a full Chromium instance + LLM calls, so this prevents
# resource exhaustion under burst traffic.
_MAX_CONCURRENT_SESSIONS = int(os.environ.get("MAX_CONCURRENT_SESSIONS", "3"))
_session_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SESSIONS)


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
    storage: tracking_data.CapturedStorage = dataclasses.field(default_factory=tracking_data.CapturedStorage)
    screenshot: bytes = b""
    pre_consent_stats: analysis.PreConsentStats | None = None
    consent_details: consent.ConsentDetails | None = None
    overlay_count: int = 0
    overlay_result: overlay_pipeline.OverlayHandlingResult | None = None
    decoded_cookies: dict[str, object] | None = None
    aborted: bool = False


async def _take_targeted_screenshot(
    session: browser_session.BrowserSession,
    label: str,
) -> str | None:
    """Take a single screenshot and return a ``screenshotUpdate`` SSE event.

    Returns ``None`` if the screenshot fails (e.g. the page is
    unresponsive).  This is a lightweight helper for the two
    targeted refresh points: after no-dialog detection and after
    the page settle process before analysis.
    """
    try:
        raw = await session.take_screenshot(full_page=False)
        optimized = browser_session.BrowserSession.optimize_screenshot_bytes(raw)
        log.debug("Targeted screenshot refresh", {"point": label})
        return sse_helpers.format_screenshot_update_event(optimized)
    except Exception as exc:
        log.debug(
            "Targeted screenshot failed — skipping",
            {"point": label, "error": str(exc)},
        )
        return None


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

    # ── SSRF prevention ─────────────────────────────────────
    try:
        await url_mod.validate_analysis_url(url)
    except url_mod.UnsafeURLError as exc:
        log.error("URL rejected by safety check", {"url": url, "reason": str(exc)})
        yield sse_helpers.format_sse_event("error", {"error": str(exc)})
        return

    # ── Concurrency gate ────────────────────────────────────
    if _session_semaphore.locked():
        log.warn("Concurrent session limit reached", {"limit": _MAX_CONCURRENT_SESSIONS})
        yield sse_helpers.format_sse_event(
            "error",
            {"error": f"Server is busy — maximum {_MAX_CONCURRENT_SESSIONS} concurrent analyses. Please try again shortly."},
        )
        return

    async with _session_semaphore:
        async for event in _run_analysis(url, device_type, clear_cache):
            yield event


# ====================================================================
# Session cleanup
# ====================================================================


async def _cleanup_session(
    ctx: _StreamContext,
    session: browser_session.BrowserSession,
) -> None:
    """Release all resources for a single analysis run.

    Called at the end of ``_run_analysis`` (in the ``finally``
    block).  Closes the ``BrowserContext`` (fast ~50 ms) and
    logs completion.  Catches all exceptions internally —
    callers never see errors.
    """
    log.debug("Cleaning up browser resources...")

    # Close the context with a hard timeout so a hung
    # renderer cannot block the server indefinitely.
    # BrowserSession.close() has its own per-step timeouts;
    # this outer guard covers the aggregate case.
    try:
        await asyncio.wait_for(session.close(), timeout=30)
    except TimeoutError:
        log.error(
            "Browser cleanup timed out after 30s — resources may have leaked",
        )
    except Exception as err:
        log.warn(
            "Error during browser cleanup",
            {"error": errors.get_error_message(err)},
        )
    log.debug("Browser cleanup complete")


# ====================================================================
# Core analysis generator
# ====================================================================


async def _run_analysis(
    url: str,
    device_type: browser.DeviceType,
    clear_cache: bool,
) -> AsyncGenerator[str]:
    """Core analysis loop — runs inside the concurrency semaphore."""
    domain = url_mod.extract_domain(url)
    hostname = parse.urlparse(url).hostname or url
    logger.clear_timers()
    logger.start_log_file(domain)

    usage_tracking.reset()
    log.section(f"Analyzing: {url}")
    log.info("Server version", {"version": _SERVER_VERSION})
    log.info("Request received", {"url": url, "device": device_type})

    if clear_cache:
        log.success("All caches cleared by user request")
        yield sse_helpers.format_progress_event("cache-cleared", "Caches cleared!", 2)

    # Create a session from the shared browser (fast: ~50 ms).
    # The PlaywrightManager reuses the Chrome instance started
    # at app startup and creates an isolated BrowserContext.
    yield sse_helpers.format_progress_event("init", "Warming up the browser...", 5)
    manager = browser_manager.PlaywrightManager.get_instance()
    session = await manager.create_session(device_type)
    session.set_current_page_url(url)

    ctx = _StreamContext(
        session=session,
        url=url,
        hostname=hostname,
        domain=domain,
        device_type=device_type,
    )

    log.start_timer("total-analysis")
    analysis_start = asyncio.get_running_loop().time()

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
            total_time = log.end_timer("total-analysis", "Analysis complete")
            log.success(
                "Investigation complete",
                {
                    "totalTime": f"{(total_time / 1000):.2f}s",
                    "overlaysDismissed": ctx.overlay_count,
                },
            )

    except TimeoutError:
        elapsed = asyncio.get_running_loop().time() - analysis_start
        elapsed_str = f"{int(elapsed)} seconds" if elapsed < 120 else f"{elapsed / 60:.1f} minutes"
        log.error(
            "Analysis timed out",
            {"elapsed_seconds": int(elapsed), "limit_seconds": STREAM_TIMEOUT_SECONDS},
        )
        yield sse_helpers.format_sse_event(
            "error",
            {"error": f"Analysis timed out after {elapsed_str}"},
        )
    except Exception as error:
        log.error(
            "Analysis failed with exception",
            {"error": errors.get_error_message(error)},
        )
        yield sse_helpers.format_sse_event(
            "error",
            {"error": errors.get_safe_client_message(error)},
        )
    finally:
        # Perform cleanup eagerly so all log messages appear
        # *before* the generator returns — preventing the
        # event-loop from interleaving a new request's logs
        # with the old run's cleanup messages.
        #
        # CancelledError is a BaseException in Python 3.9+
        # and is NOT caught by 'except Exception'.  Wrap
        # the entire block so that end_log_file() always runs.
        try:
            usage_tracking.log_summary()
            await _cleanup_session(ctx, session)
        except BaseException as exc:
            log.warn("Cleanup interrupted", {"error": str(exc)})
        finally:
            logger.end_log_file()


# ====================================================================
# Phase helpers — each yields SSE events and mutates ctx
# ====================================================================


async def _run_phases_1_to_3(ctx: _StreamContext) -> AsyncGenerator[str]:
    """Phases 1–3: navigation, page load, data capture.

    The browser session is already created (shared Chrome, isolated
    context) by ``_run_analysis``.  This function navigates to the
    target URL and captures the initial page state.

    Sets ``ctx.aborted`` if navigation fails or access is denied.
    Populates ``ctx.storage``, ``ctx.screenshot``, and
    ``ctx.pre_consent_stats``.
    """
    session = ctx.session

    # ── Phase 1: Navigation ─────────────────────────────
    log.subsection("Phase 1: Browser Setup")
    log.info("Navigating to page", {"url": ctx.url, "device": ctx.device_type})

    yield sse_helpers.format_progress_event("navigate", f"Loading {ctx.hostname}...", 12)
    nav_result = await browser_phases.navigate(session, ctx.url)

    if not nav_result.success:
        for event in _emit_nav_failure(nav_result):
            yield event
        ctx.aborted = True
        return

    # ── Phase 2: Page Load & Access Check ───────────────
    log.subsection("Phase 2: Page Load & Access Check")

    yield sse_helpers.format_progress_event("wait-network", f"Waiting for {ctx.hostname} to settle...", 18)
    await browser_phases.wait_for_network_settle(session)

    yield sse_helpers.format_progress_event("wait-content", "Waiting for page content to render...", 25)
    await browser_phases.wait_for_content_render(session)

    access_events, denied = await browser_phases.check_access(session, nav_result)
    for event in access_events:
        yield event
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

    # Snapshot page-load data before any overlay is dismissed.
    ctx.pre_consent_stats = tracking_summary.build_pre_consent_stats(
        session.get_tracked_cookies(),
        session.get_tracked_scripts(),
        session.get_tracked_network_requests(),
        ctx.storage,
    )
    log.info(
        "Pre-consent stats captured",
        {
            "cookies": ctx.pre_consent_stats.total_cookies,
            "trackingCookies": ctx.pre_consent_stats.tracking_cookies,
            "scripts": ctx.pre_consent_stats.total_scripts,
            "trackingScripts": ctx.pre_consent_stats.tracking_scripts,
            "requests": ctx.pre_consent_stats.total_requests,
            "trackerRequests": ctx.pre_consent_stats.tracker_requests,
        },
    )

    # Tag every request captured so far as pre-consent.
    for req in session.get_tracked_network_requests():
        req.pre_consent = True


# ── Phase-4 helpers ─────────────────────────────────────────


def _decode_consent_strings(ctx: _StreamContext) -> list[str]:
    """Decode TC/AC consent strings from cookies and storage.

    Runs a 5-tier cascade to discover and decode the
    ``euconsent-v2`` and ``addtl_consent`` values set by the
    CMP after consent is accepted.  Mutates
    ``ctx.consent_details`` in-place with the decoded data.

    Returns:
        SSE event strings to yield to the client.
    """
    assert ctx.consent_details is not None  # caller guarantees
    events: list[str] = []
    session = ctx.session

    tracked_cookies = session.get_tracked_cookies()
    local_storage = ctx.storage.local_storage if ctx.storage else []

    # Resolve CMP profile for tier-2 lookups
    cmp_profile = platform_detection.detect_platform_from_cookies(
        [c.model_dump() for c in tracked_cookies],
    )
    tc_sources = cmp_profile.tc_string_sources if cmp_profile else {}

    # Back-fill consent_platform when not set during
    # the overlay loop (CMP cookies may only appear
    # after dismissing the consent dialog).
    if cmp_profile and not ctx.consent_details.consent_platform:
        ctx.consent_details.consent_platform = cmp_profile.name
        log.info(
            "Late CMP detection — back-filling consent platform",
            {"platform": cmp_profile.name, "key": cmp_profile.key},
        )
        # Update the overlay cache so future runs
        # have the correct platform key.
        overlay_cache.backfill_consent_platform(
            ctx.domain,
            cmp_profile.key,
        )

    # ── AC String decoding ───────────────────────────
    # The addtl_consent cookie stores Google's
    # Additional Consent Mode string — a list of
    # non-IAB ad-tech providers that received consent
    # through a Google-certified CMP.  Decode first so
    # the vendor count is available for TC validation.
    ac_vendor_count: int | None = None

    ac_result_pair = _discover_consent_string(
        _AC_TIERS,
        tracked_cookies,
        local_storage,
        tc_sources,
    )

    if ac_result_pair:
        ac_source, ac_raw_value = ac_result_pair
        ac_decoded = tc_string.decode_ac_string(ac_raw_value)
        if ac_decoded:
            ac_data = ac_decoded.model_dump(by_alias=True)

            # Resolve ATP provider IDs to names
            ac_result = vendor_lookup.resolve_ac_providers(
                ac_decoded.vendor_ids,
            )
            ac_data["resolvedProviders"] = [dict(p) for p in ac_result["resolved"]]
            ac_data["unresolvedProviderCount"] = ac_result["unresolved_count"]

            ctx.consent_details.ac_string_data = ac_data
            ac_vendor_count = ac_decoded.vendor_count
            log.info(
                f"AC String decoded from {ac_source}",
                {
                    "version": ac_decoded.version,
                    "vendorCount": ac_decoded.vendor_count,
                },
            )

    # ── TC String decoding ───────────────────────

    tc_result_pair = _discover_consent_string(
        _TC_TIERS,
        tracked_cookies,
        local_storage,
        tc_sources,
    )
    if tc_result_pair:
        tc_source, tc_raw = tc_result_pair
        decoded = tc_string.decode_tc_string(tc_raw)
        if decoded:
            tc_data = decoded.model_dump(
                by_alias=True,
            )

            # Resolve GVL vendor IDs to names
            consent_result = vendor_lookup.resolve_gvl_vendors(
                decoded.vendor_consents,
            )
            li_result = vendor_lookup.resolve_gvl_vendors(
                decoded.vendor_legitimate_interests,
            )
            tc_data["resolvedVendorConsents"] = [dict(v) for v in consent_result["resolved"]]
            tc_data["unresolvedVendorConsentCount"] = consent_result["unresolved_count"]
            tc_data["resolvedVendorLi"] = [dict(v) for v in li_result["resolved"]]
            tc_data["unresolvedVendorLiCount"] = li_result["unresolved_count"]

            ctx.consent_details.tc_string_data = tc_data
            log.info(
                f"TC String decoded from {tc_source}",
                {
                    "version": decoded.version,
                    "cmpId": decoded.cmp_id,
                    "vendorListVersion": decoded.vendor_list_version,
                    "purposeConsents": decoded.purpose_consents,
                    "vendorConsentCount": decoded.vendor_consent_count,
                    "vendorLiCount": decoded.vendor_li_count,
                },
            )

            # ── TC String validation ─────────────────
            # Cross-reference TC String signals against
            # the dialog-extracted purpose text to detect
            # discrepancies and privacy-relevant signals.
            dialog_purposes = ctx.consent_details.purposes
            lookup_result = tcf_lookup.lookup_purposes(dialog_purposes)
            matched_ids = {m.id for m in lookup_result.matched if m.category == "purpose"}
            validation = tc_validation.validate_tc_consent(
                tc_string_data=ctx.consent_details.tc_string_data,
                dialog_purposes=dialog_purposes,
                matched_purpose_ids=matched_ids,
                claimed_partner_count=ctx.consent_details.claimed_partner_count,
                ac_vendor_count=ac_vendor_count,
                detected_cmp_id=cmp_profile.cmp_id if cmp_profile else None,
            )
            ctx.consent_details.tc_validation = validation.model_dump(
                by_alias=True,
            )
            if validation.findings:
                log.info(
                    "TC validation findings",
                    {
                        "count": len(validation.findings),
                        "severities": [f.severity for f in validation.findings],
                    },
                )

    # Re-emit consent details with TC/AC data
    if ctx.consent_details.tc_string_data or ctx.consent_details.ac_string_data:
        events.append(
            sse_helpers.format_sse_event(
                "consentDetails",
                sse_helpers.serialize_consent_details(
                    ctx.consent_details,
                ),
            )
        )

    return events


def _decode_privacy_cookies(ctx: _StreamContext) -> list[str]:
    """Decode privacy-relevant cookie signals.

    Scans all captured cookies for USP, GPP, GA, Facebook,
    Google Ads, OneTrust, Cookiebot, Google SOCS, etc.
    regardless of whether a consent dialog was found.

    Returns:
        SSE event strings to yield to the client.
    """
    events: list[str] = []
    session = ctx.session

    tracked = session.get_tracked_cookies()
    if tracked:
        decoded_cookies = cookie_decoders.decode_all_privacy_cookies(tracked)
        if decoded_cookies:
            ctx.decoded_cookies = decoded_cookies
            log.info(
                "Privacy cookies decoded",
                {"decoders": list(decoded_cookies.keys())},
            )
            events.append(
                sse_helpers.format_sse_event(
                    "decodedCookies",
                    decoded_cookies,
                )
            )

    return events


def _handle_overlay_failure(ctx: _StreamContext) -> list[str]:
    """Check for overlay dismissal failure and abort if fatal.

    When the overlay click failed but consent data was
    captured, analysis continues.  Otherwise ``ctx.aborted``
    is set and the returned events signal the error.

    Returns:
        SSE event strings to yield to the client.
    """
    events: list[str] = []
    page = ctx.session.get_page()

    if page and ctx.overlay_result and ctx.overlay_result.failed:
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
            events.append(
                sse_helpers.format_sse_event(
                    "pageError",
                    {
                        "type": "overlay-blocked",
                        "message": ctx.overlay_result.failure_message,
                        "isOverlayBlocked": True,
                    },
                )
            )
            events.append(
                sse_helpers.format_progress_event(
                    "overlay-blocked",
                    "Could not dismiss page overlay!",
                    100,
                )
            )
            ctx.aborted = True

    return events


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

    if ctx.consent_details:
        log.info(
            "Consent details summary",
            {
                "categories": len(ctx.consent_details.categories),
                "partners": len(ctx.consent_details.partners),
                "purposes": len(ctx.consent_details.purposes),
                "claimedPartnerCount": ctx.consent_details.claimed_partner_count,
                "consentPlatform": ctx.consent_details.consent_platform,
            },
        )

    # Post-overlay capture — re-capture page state only when
    # overlays *were* dismissed, since the page will have changed.
    # When no overlays were found the page is unchanged from the
    # initial capture (Phase 3), so we skip the redundant work.
    if ctx.overlay_count > 0:
        yield sse_helpers.format_progress_event(
            "post-overlay-capture",
            "Capturing page data...",
            72,
        )
        await session.capture_current_cookies()
        ctx.storage = await session.capture_storage()

        # Decode TC/AC consent strings from the freshly-
        # captured cookies and storage.
        if ctx.consent_details is not None:
            for event in _decode_consent_strings(ctx):
                yield event

    else:
        log.info("No overlays dismissed — page state unchanged, skipping re-capture")
        # Targeted screenshot refresh — ads and deferred
        # content should have loaded by now.
        refresh_event = await _take_targeted_screenshot(session, "no-dialog")
        if refresh_event:
            yield refresh_event

    # ── Privacy cookie decoding ──────────────────────────
    for event in _decode_privacy_cookies(ctx):
        yield event

    # ── Overlay failure check ────────────────────────────
    for event in _handle_overlay_failure(ctx):
        yield event
    if ctx.aborted:
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

    # Targeted screenshot refresh — ads and deferred content
    # should have loaded by now.
    refresh_event = await _take_targeted_screenshot(session, "pre-analysis")
    if refresh_event:
        yield refresh_event

    yield sse_helpers.format_progress_event(
        "pre-analysis",
        "Preparing analysis...",
        74,
    )


async def _run_phase_5_analysis(ctx: _StreamContext) -> AsyncGenerator[str]:
    """Phase 5: AI analysis."""
    session = ctx.session

    # ── AI Analysis ────────────────────────────────────
    log.subsection("Phase 5: AI Analysis")

    async for event in analysis_pipeline.run_ai_analysis(
        session,
        ctx.storage,
        ctx.url,
        ctx.consent_details,
        ctx.pre_consent_stats,
        decoded_cookies=ctx.decoded_cookies,
    ):
        yield event


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
