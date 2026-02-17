"""
AI analysis pipeline — concurrent script + tracking analysis.

Runs script grouping/identification and LLM tracking analysis in
parallel, then scores results and generates summary findings.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from src import agents
from src.analysis import domain_cache, scripts, tracking
from src.analysis import tracking_summary as tracking_summary_mod
from src.analysis.scoring import calculator
from src.browser import session as browser_session
from src.models import analysis, consent, tracking_data
from src.models import report as report_models
from src.pipeline import sse_helpers
from src.utils import logger, usage_tracking
from src.utils import url as url_mod

log = logger.create_logger("Analysis")

# Collection caps for the SSE ``complete`` payload — keep it under ~1 MB.
_MAX_DOMAIN_BREAKDOWN = 100
_MAX_SCRIPTS = 200
_MAX_SCRIPT_GROUPS = 100
_MAX_STORAGE_ITEMS = 100


async def run_ai_analysis(
    session: browser_session.BrowserSession,
    storage: dict[str, list[tracking_data.StorageItem]],
    url: str,
    consent_details: consent.ConsentDetails | None,
    overlay_count: int = 0,
    pre_consent_stats: analysis.PreConsentStats | None = None,
) -> AsyncGenerator[str]:
    """Run script and tracking analysis concurrently.

    Streams SSE events (progress + analysis chunks) as they
    become available, then yields scoring, summary, and the
    final ``complete`` event.
    """
    # Capture the latest cookies from the browser context.
    # Earlier phases capture cookies at specific checkpoints
    # (initial load, after overlay click) but deferred scripts
    # and post-consent tracking may have added more since then.
    await session.capture_current_cookies()

    # Snapshot the live tracking lists so that scripts
    # arriving during analysis (ad networks, deferred
    # pixels) don't create inconsistent counts between
    # the analysis input and the reported totals.
    final_cookies = list(session.get_tracked_cookies())
    final_scripts = list(session.get_tracked_scripts())
    final_requests = list(session.get_tracked_network_requests())

    log.info(
        "Final data snapshot",
        {
            "cookies": len(final_cookies),
            "scripts": len(final_scripts),
            "requests": len(final_requests),
        },
    )
    yield sse_helpers.format_progress_event(
        "analysis-start",
        "Analyzing page content...",
        75,
    )

    log.start_timer("ai-analysis")

    # ── Launch concurrent tasks and yield events in real-time ──
    progress_queue: asyncio.Queue[str | None] = asyncio.Queue()
    analysis_chunks: list[str] = []

    script_task, tracking_task = _launch_concurrent_tasks(
        progress_queue,
        final_cookies,
        final_scripts,
        final_requests,
        storage,
        url,
        consent_details,
        analysis_chunks,
        pre_consent_stats,
    )

    # Drain events as they arrive — this keeps SSE streaming
    # in real-time rather than batching.
    tasks_remaining = 2
    finished = 0
    while finished < tasks_remaining:
        event = await progress_queue.get()
        if event is None:
            finished += 1
            continue
        yield event

    await script_task
    await tracking_task
    script_result = script_task.result()

    log.end_timer("tracking-analysis", "Tracking analysis complete")

    # ── Scoring and summary ─────────────────────────────────
    async for event in _score_and_summarise(
        final_cookies,
        final_scripts,
        final_requests,
        storage,
        url,
        consent_details,
        overlay_count,
        analysis_chunks,
        script_result,
        pre_consent_stats,
    ):
        yield event


def _launch_concurrent_tasks(
    progress_queue: asyncio.Queue[str | None],
    final_cookies: list[tracking_data.TrackedCookie],
    final_scripts: list[tracking_data.TrackedScript],
    final_requests: list[tracking_data.NetworkRequest],
    storage: dict[str, list[tracking_data.StorageItem]],
    url: str,
    consent_details: consent.ConsentDetails | None,
    analysis_chunks: list[str],
    pre_consent_stats: analysis.PreConsentStats | None = None,
) -> tuple[asyncio.Task[scripts.ScriptAnalysisResult], asyncio.Task[None]]:
    """Create and launch the concurrent script + tracking tasks.

    Both tasks push SSE event strings (or ``None`` sentinels) onto
    *progress_queue*.  The caller is responsible for draining the
    queue to keep events streaming in real-time.

    Returns:
        Tuple of (script_task, tracking_task).
    """
    log.start_timer("script-analysis")

    def _script_progress(phase: str, current: int, total: int, detail: str) -> None:
        log.info(f"Script analysis progress: {phase} {current}/{total} - {detail}")
        if phase == "matching":
            if current == 0:
                progress_queue.put_nowait(
                    sse_helpers.format_progress_event(
                        "script-matching",
                        detail or "Grouping and identifying scripts...",
                        77,
                    )
                )
        elif phase == "fetching":
            pct = 77 + int((current / max(total, 1)) * 2)
            progress_queue.put_nowait(
                sse_helpers.format_progress_event(
                    "script-fetching",
                    detail or f"Fetching script {current}/{total}...",
                    pct,
                )
            )
        elif phase == "analyzing":
            if total == 0:
                progress_queue.put_nowait(
                    sse_helpers.format_progress_event(
                        "script-analysis",
                        detail or "Analyzing scripts...",
                        82,
                    )
                )
            else:
                pct = 79 + int((current / total) * 11)
                progress_queue.put_nowait(
                    sse_helpers.format_progress_event(
                        "script-analysis",
                        detail or f"Analyzing script {current}/{total}...",
                        pct,
                    )
                )

    async def _run_scripts() -> scripts.ScriptAnalysisResult:
        try:
            result = await scripts.analyze_scripts(final_scripts, _script_progress)
            log.end_timer(
                "script-analysis",
                f"Script analysis complete... ({len(result.scripts)} scripts, {len(result.groups)} groups)",
            )
            return result
        finally:
            progress_queue.put_nowait(None)

    log.start_timer("tracking-analysis")

    async def _run_tracking() -> None:
        try:
            async for chunk in tracking.stream_tracking_analysis(
                final_cookies,
                storage["local_storage"],
                storage["session_storage"],
                final_requests,
                final_scripts,
                url,
                consent_details,
                pre_consent_stats,
            ):
                analysis_chunks.append(chunk)
                progress_queue.put_nowait(sse_helpers.format_sse_event("analysis-chunk", {"text": chunk}))
        finally:
            progress_queue.put_nowait(None)

    script_task = asyncio.create_task(_run_scripts())
    tracking_task = asyncio.create_task(_run_tracking())

    return script_task, tracking_task


# ============================================================================
# Report rendering helpers — one per section
# ============================================================================

_SECTION_DIVIDER = "─" * 40


def _render_header(
    url: str,
    score: int,
    score_summary: str,
) -> list[str]:
    """Render the report header with URL and score."""
    now = datetime.now(UTC)
    return [
        "=" * 72,
        f"  Privacy Analysis Report — {url}",
        f"  Generated: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "=" * 72,
        "",
        f"Privacy Score: {score}/100",
        score_summary,
        "",
    ]


def _render_score_breakdown(
    score_breakdown: analysis.ScoreBreakdown | None,
) -> list[str]:
    """Render the score category breakdown section."""
    if not score_breakdown or not score_breakdown.categories:
        return []
    lines = [_SECTION_DIVIDER, "SCORE BREAKDOWN", _SECTION_DIVIDER]
    for cat_name, cat_score in score_breakdown.categories.items():
        lines.append(f"  {cat_name}: {cat_score.points}/{cat_score.max_points}")
        for issue in cat_score.issues:
            lines.append(f"    - {issue}")
    if score_breakdown.factors:
        lines.append("\n  Key factors:")
        for factor in score_breakdown.factors:
            lines.append(f"    • {factor}")
    lines.append("")
    return lines


def _render_pre_consent_stats(
    pre_consent_stats: analysis.PreConsentStats | None,
) -> list[str]:
    """Render the pre-consent tracking stats section."""
    if not pre_consent_stats:
        return []
    return [
        _SECTION_DIVIDER,
        "PRE-CONSENT TRACKING",
        _SECTION_DIVIDER,
        f"  Cookies: {pre_consent_stats.total_cookies} (tracking: {pre_consent_stats.tracking_cookies})",
        f"  Scripts: {pre_consent_stats.total_scripts} (tracking: {pre_consent_stats.tracking_scripts})",
        f"  Requests: {pre_consent_stats.total_requests} (tracker: {pre_consent_stats.tracker_requests})",
        f"  localStorage: {pre_consent_stats.total_local_storage} items",
        f"  sessionStorage: {pre_consent_stats.total_session_storage} items",
        "",
    ]


def _render_summary_findings(
    summary_findings: list[analysis.SummaryFinding],
) -> list[str]:
    """Render the summary findings section."""
    if not summary_findings:
        return []
    lines = [_SECTION_DIVIDER, "SUMMARY", _SECTION_DIVIDER]
    for f in summary_findings:
        lines.append(f"  [{f.type.upper()}] {f.text}")
    lines.append("")
    return lines


def _render_privacy_risk(
    report: report_models.StructuredReport,
) -> list[str]:
    """Render the privacy risk assessment section."""
    risk = report.privacy_risk
    if not risk.summary:
        return []
    lines = [
        _SECTION_DIVIDER,
        f"PRIVACY RISK ASSESSMENT — {risk.overall_risk.upper()}",
        _SECTION_DIVIDER,
        risk.summary,
    ]
    for rf in risk.factors:
        lines.append(f"  [{rf.severity.upper()}] {rf.description}")
    lines.append("")
    return lines


def _render_tracking_technologies(
    report: report_models.StructuredReport,
) -> list[str]:
    """Render the tracking technologies section."""
    tech = report.tracking_technologies
    all_trackers = tech.analytics + tech.advertising + tech.identity_resolution + tech.social_media + tech.other
    if not all_trackers:
        return []
    lines = [_SECTION_DIVIDER, "TRACKING TECHNOLOGIES", _SECTION_DIVIDER]
    for cat_name, cat_list in [
        ("Analytics", tech.analytics),
        ("Advertising", tech.advertising),
        ("Identity Resolution", tech.identity_resolution),
        ("Social Media", tech.social_media),
        ("Other", tech.other),
    ]:
        if cat_list:
            lines.append(f"\n  {cat_name}:")
            for t in cat_list:
                lines.append(f"    • {t.name}: {t.purpose}")
    lines.append("")
    return lines


def _render_data_collection(
    report: report_models.StructuredReport,
) -> list[str]:
    """Render the data collection section."""
    if not report.data_collection.items:
        return []
    lines = [_SECTION_DIVIDER, "DATA COLLECTION", _SECTION_DIVIDER]
    for item in report.data_collection.items:
        sens = " [SENSITIVE]" if item.sensitive else ""
        lines.append(f"  {item.category} ({item.risk}){sens}")
        for d in item.details:
            lines.append(f"    - {d}")
        if item.shared_with:
            lines.append(f"    Shared with: {', '.join(e.name for e in item.shared_with)}")
    lines.append("")
    return lines


def _render_third_party_services(
    report: report_models.StructuredReport,
) -> list[str]:
    """Render the third-party services section."""
    tp = report.third_party_services
    if not tp.groups:
        return []
    lines = [_SECTION_DIVIDER, f"THIRD-PARTY SERVICES ({tp.total_domains} domains)", _SECTION_DIVIDER]
    for tpg in tp.groups:
        lines.append(f"  {tpg.category}: {', '.join(e.name for e in tpg.services)}")
        lines.append(f"    Impact: {tpg.privacy_impact}")
    if tp.summary:
        lines.append(f"\n  {tp.summary}")
    lines.append("")
    return lines


def _render_cookie_analysis(
    report: report_models.StructuredReport,
) -> list[str]:
    """Render the cookie analysis section."""
    cookie_sec = report.cookie_analysis
    if not cookie_sec.groups:
        return []
    lines = [_SECTION_DIVIDER, f"COOKIE ANALYSIS ({cookie_sec.total} cookies)", _SECTION_DIVIDER]
    for cookie_grp in cookie_sec.groups:
        lines.append(
            f"  {cookie_grp.category} ({cookie_grp.concern_level}): "
            f"{', '.join(cookie_grp.cookies[:10])}"
            f"{'...' if len(cookie_grp.cookies) > 10 else ''}"
        )
    if cookie_sec.concerning_cookies:
        lines.append("\n  Concerning cookies:")
        for concern_cookie in cookie_sec.concerning_cookies:
            lines.append(f"    • {concern_cookie}")
    lines.append("")
    return lines


def _render_storage_analysis(
    report: report_models.StructuredReport,
) -> list[str]:
    """Render the storage analysis section."""
    sa = report.storage_analysis
    if not sa.local_storage_count and not sa.session_storage_count:
        return []
    lines = [
        _SECTION_DIVIDER,
        "STORAGE ANALYSIS",
        _SECTION_DIVIDER,
        f"  localStorage: {sa.local_storage_count} items",
        f"  sessionStorage: {sa.session_storage_count} items",
    ]
    for concern in sa.local_storage_concerns:
        lines.append(f"    [localStorage] {concern}")
    for concern in sa.session_storage_concerns:
        lines.append(f"    [sessionStorage] {concern}")
    if sa.summary:
        lines.append(f"\n  {sa.summary}")
    lines.append("")
    return lines


def _render_consent_analysis(
    report: report_models.StructuredReport,
    consent_details: consent.ConsentDetails | None,
) -> list[str]:
    """Render the consent analysis section."""
    consent_sec = report.consent_analysis
    if not consent_sec.has_consent_dialog and not consent_sec.discrepancies:
        return []
    lines = [
        _SECTION_DIVIDER,
        "CONSENT ANALYSIS",
        _SECTION_DIVIDER,
        f"  Consent dialog: {'Yes' if consent_sec.has_consent_dialog else 'No'}",
    ]
    if consent_sec.consent_platform:
        platform_line = f"  Consent platform: {consent_sec.consent_platform}"
        if consent_sec.consent_platform_url:
            platform_line += f" ({consent_sec.consent_platform_url})"
        lines.append(platform_line)
    if consent_sec.categories_disclosed:
        lines.append(f"  Categories disclosed: {consent_sec.categories_disclosed}")
    if consent_sec.partners_disclosed:
        lines.append(f"  Partners disclosed: {consent_sec.partners_disclosed}")
    if consent_details:
        if consent_details.categories:
            lines.append(f"  Consent categories: {len(consent_details.categories)}")
            for cat in consent_details.categories[:10]:
                lines.append(f"    • {cat.name}")
            if len(consent_details.categories) > 10:
                lines.append(f"    ... and {len(consent_details.categories) - 10} more")
        if consent_details.partners:
            lines.append(f"  Consent partners: {len(consent_details.partners)}")
            for partner in consent_details.partners[:10]:
                risk_tag = f" [{partner.risk_level}]" if partner.risk_level else ""
                lines.append(f"    • {partner.name}{risk_tag}")
            if len(consent_details.partners) > 10:
                lines.append(f"    ... and {len(consent_details.partners) - 10} more")
        if consent_details.claimed_partner_count is not None:
            lines.append(f"  Claimed partner count: {consent_details.claimed_partner_count}")
    for disc in consent_sec.discrepancies:
        lines.append(f"  [{disc.severity.upper()}] Claimed: {disc.claimed}")
        lines.append(f"    Actual: {disc.actual}")
    if consent_sec.summary:
        lines.append(f"\n  {consent_sec.summary}")
    lines.append("")
    return lines


def _render_key_vendors(
    report: report_models.StructuredReport,
) -> list[str]:
    """Render the key vendors section."""
    if not report.key_vendors.vendors:
        return []
    lines = [_SECTION_DIVIDER, "TOP VENDORS AND PARTNERS", _SECTION_DIVIDER]
    for v in report.key_vendors.vendors:
        if v.url:
            lines.append(f"  • {v.name} ({v.role}) — {v.url}")
        else:
            lines.append(f"  • {v.name} ({v.role})")
        lines.append(f"    {v.privacy_impact}")
    lines.append("")
    return lines


def _render_recommendations(
    report: report_models.StructuredReport,
) -> list[str]:
    """Render the recommendations section."""
    if not report.recommendations.groups:
        return []
    lines = [_SECTION_DIVIDER, "RECOMMENDATIONS", _SECTION_DIVIDER]
    for rg in report.recommendations.groups:
        lines.append(f"\n  {rg.category}:")
        for rec in rg.items:
            lines.append(f"    • {rec}")
    lines.append("")
    return lines


def _render_llm_usage() -> list[str]:
    """Render the LLM usage summary section."""
    summary = usage_tracking.get_summary()
    if summary.total_calls == 0:
        return []
    lines = [
        _SECTION_DIVIDER,
        "LLM USAGE",
        _SECTION_DIVIDER,
        f"  Total LLM calls: {summary.total_calls}",
        f"  Input tokens:    {summary.total_input_tokens:,}",
        f"  Output tokens:   {summary.total_output_tokens:,}",
        f"  Total tokens:    {summary.total_tokens:,}",
        "",
    ]
    return lines


def _render_report_text(
    url: str,
    score: int,
    score_summary: str,
    summary_findings: list[analysis.SummaryFinding],
    report: report_models.StructuredReport,
    score_breakdown: analysis.ScoreBreakdown | None = None,
    consent_details: consent.ConsentDetails | None = None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
) -> str:
    """Render the structured report as a plain-text file.

    Produces a human-readable text version of the complete
    analysis for archival purposes.
    """
    lines: list[str] = _render_header(url, score, score_summary)
    lines += _render_score_breakdown(score_breakdown)
    lines += _render_pre_consent_stats(pre_consent_stats)
    lines += _render_summary_findings(summary_findings)
    lines += _render_privacy_risk(report)
    lines += _render_tracking_technologies(report)
    lines += _render_data_collection(report)
    lines += _render_third_party_services(report)
    lines += _render_cookie_analysis(report)
    lines += _render_storage_analysis(report)
    lines += _render_consent_analysis(report, consent_details)
    lines += _render_key_vendors(report)
    lines += _render_recommendations(report)
    lines += _render_llm_usage()
    lines.append("=" * 72)
    return "\n".join(lines)


async def _score_and_summarise(
    final_cookies: list[tracking_data.TrackedCookie],
    final_scripts: list[tracking_data.TrackedScript],
    final_requests: list[tracking_data.NetworkRequest],
    storage: dict[str, list[tracking_data.StorageItem]],
    url: str,
    consent_details: consent.ConsentDetails | None,
    overlay_count: int,
    analysis_chunks: list[str],
    script_result: scripts.ScriptAnalysisResult,
    pre_consent_stats: analysis.PreConsentStats | None = None,
) -> AsyncGenerator[str]:
    """Score, summarise, and yield the complete event."""
    full_text = "".join(analysis_chunks)
    log.info("Analysis streamed", {"length": len(full_text)})

    yield sse_helpers.format_progress_event("ai-scoring", "Calculating privacy score...", 94)

    tracking_summary = tracking_summary_mod.build_tracking_summary(
        final_cookies,
        final_scripts,
        final_requests,
        storage["local_storage"],
        storage["session_storage"],
        url,
    )

    score_breakdown = calculator.calculate_privacy_score(
        final_cookies,
        final_scripts,
        final_requests,
        storage["local_storage"],
        storage["session_storage"],
        url,
        consent_details,
        pre_consent_stats,
    )
    log.info(
        "Privacy score calculated",
        {"score": score_breakdown.total_score},
    )

    yield sse_helpers.format_progress_event("ai-summarizing", "Generating summary...", 96)
    log.info("Starting summary and report generation")

    # Build structured report and summary findings concurrently
    report_agent = agents.get_structured_report_agent()
    summary_agent = agents.get_summary_findings_agent()

    # Load cached domain knowledge for consistency anchoring.
    domain = url_mod.extract_domain(url)
    domain_knowledge = domain_cache.load(domain)

    if domain_knowledge:
        log.info(
            "Domain cache hit — anchoring classifications",
            {
                "domain": domain,
                "scanCount": domain_knowledge.scan_count,
                "trackers": len(domain_knowledge.trackers),
                "vendors": len(domain_knowledge.vendors),
            },
        )
    else:
        log.info("Domain cache miss — no prior knowledge", {"domain": domain})

    structured_report_task = asyncio.create_task(
        report_agent.build_report(
            tracking_summary,
            consent_details,
            pre_consent_stats,
            score_breakdown,
            domain_knowledge,
        )
    )
    summary_task = asyncio.create_task(
        summary_agent.summarise(
            full_text,
            score_breakdown,
            domain_knowledge,
            consent_details,
            tracking_summary,
            pre_consent_stats,
        )
    )

    yield sse_helpers.format_progress_event("ai-report", "Generating report...", 97)

    try:
        structured_report, summary_findings = await asyncio.gather(
            structured_report_task,
            summary_task,
        )
    except Exception:
        # Cancel the surviving task so it doesn't leak.
        for task in (structured_report_task, summary_task):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        raise
    log.info(
        "Structured report and summary generated",
        {"summaryCount": len(summary_findings)},
    )

    # Surface a note when any core agent lacked an LLM client.
    # Under normal operation ``validate_llm_config()`` blocks the
    # stream before we reach this point, so these checks are
    # defence-in-depth for internal callers or edge cases.
    _unconfigured = [
        name
        for name, agent in (
            ("consent-detection", agents.get_consent_detection_agent()),
            ("consent-extraction", agents.get_consent_extraction_agent()),
            ("script-analysis", agents.get_script_analysis_agent()),
        )
        if not agent.is_configured
    ]
    if _unconfigured:
        summary_findings.append(
            analysis.SummaryFinding(
                type="info",
                text=(f"Some AI agents were not configured and their analysis was skipped: {', '.join(_unconfigured)}."),
            )
        )

    log.end_timer("ai-analysis", "All AI analysis complete")

    # ── Save report to file (when log-to-file is enabled) ───
    analysis_success = bool(full_text)
    privacy_score = score_breakdown.total_score

    if analysis_success and structured_report:
        report_text = _render_report_text(
            url,
            privacy_score,
            score_breakdown.summary,
            summary_findings,
            structured_report,
            score_breakdown=score_breakdown,
            consent_details=consent_details,
            pre_consent_stats=pre_consent_stats,
        )
        logger.save_report_file(domain, report_text)

        # Persist domain knowledge for future consistency.
        domain_cache.save_from_report(domain, structured_report)

    # ── Build final payload ─────────────────────────────────

    yield sse_helpers.format_progress_event("complete", "Investigation complete!", 100)

    yield _build_complete_payload(
        full_text,
        structured_report,
        summary_findings,
        score_breakdown,
        tracking_summary,
        consent_details,
        script_result,
        overlay_count,
        final_cookies=final_cookies,
        final_requests=final_requests,
        storage=storage,
    )


def _build_complete_payload(
    full_text: str,
    structured_report: report_models.StructuredReport | None,
    summary_findings: list[analysis.SummaryFinding],
    score_breakdown: analysis.ScoreBreakdown,
    tracking_summary: analysis.TrackingSummary,
    consent_details: consent.ConsentDetails | None,
    script_result: scripts.ScriptAnalysisResult,
    overlay_count: int,
    final_cookies: list[tracking_data.TrackedCookie] | None = None,
    final_requests: list[tracking_data.NetworkRequest] | None = None,
    storage: dict[str, list[tracking_data.StorageItem]] | None = None,
) -> str:
    """Build the final SSE ``complete`` event payload.

    Large collections (domain breakdown, scripts, groups) are
    capped to prevent multi-MB SSE events on sites with
    hundreds of third-party scripts.
    """
    analysis_success = bool(full_text)
    privacy_score = score_breakdown.total_score

    if analysis_success:
        log.success(
            "Analysis succeeded",
            {
                "privacyScore": privacy_score,
                "analysisLength": len(full_text),
            },
        )
    else:
        log.error("Analysis produced no output")

    consent_dict = sse_helpers.serialize_consent_details(consent_details) if consent_details else None
    score_dict = sse_helpers.serialize_score_breakdown(score_breakdown) if score_breakdown else None

    return sse_helpers.format_sse_event(
        "complete",
        {
            "success": True,
            "message": ("Tracking analyzed after dismissing overlays" if overlay_count > 0 else "Tracking analyzed"),
            "analysis": full_text if analysis_success else None,
            "structuredReport": (structured_report.model_dump(by_alias=True) if analysis_success and structured_report else None),
            "summaryFindings": ([{"type": f.type, "text": f.text} for f in summary_findings] if analysis_success else None),
            "privacyScore": (privacy_score if analysis_success else None),
            "privacySummary": (score_breakdown.summary if analysis_success else None),
            "scoreBreakdown": (score_dict if analysis_success else None),
            "analysisSummary": (
                {
                    "analyzedUrl": tracking_summary.analyzed_url,
                    "totalCookies": tracking_summary.total_cookies,
                    "totalScripts": tracking_summary.total_scripts,
                    "totalNetworkRequests": tracking_summary.total_network_requests,
                    "localStorageItems": tracking_summary.local_storage_items,
                    "sessionStorageItems": tracking_summary.session_storage_items,
                    "thirdPartyDomains": tracking_summary.third_party_domains,
                    "domainBreakdown": [
                        sse_helpers.to_camel_case_dict(d) for d in tracking_summary.domain_breakdown[:_MAX_DOMAIN_BREAKDOWN]
                    ],
                    "localStorage": tracking_summary.local_storage[:_MAX_STORAGE_ITEMS],
                    "sessionStorage": tracking_summary.session_storage[:_MAX_STORAGE_ITEMS],
                }
                if tracking_summary
                else None
            ),
            "analysisError": (None if analysis_success else "Analysis produced no output"),
            "consentDetails": consent_dict,
            "cookies": [sse_helpers.to_camel_case_dict(c) for c in final_cookies] if final_cookies is not None else None,
            "networkRequests": ([sse_helpers.to_camel_case_dict(r) for r in final_requests] if final_requests is not None else None),
            "localStorage": ([sse_helpers.to_camel_case_dict(i) for i in storage["local_storage"]] if storage else None),
            "sessionStorage": ([sse_helpers.to_camel_case_dict(i) for i in storage["session_storage"]] if storage else None),
            "scripts": [sse_helpers.to_camel_case_dict(s) for s in script_result.scripts[:_MAX_SCRIPTS]],
            "scriptGroups": [sse_helpers.to_camel_case_dict(g) for g in script_result.groups[:_MAX_SCRIPT_GROUPS]],
            "debugLog": logger.get_log_buffer(),
        },
    )
