"""
AI analysis pipeline — concurrent script + tracking analysis.

Runs script grouping/identification and LLM tracking analysis in
parallel, then scores results and generates summary findings.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from src import agents
from src.analysis import domain_cache, scripts, tracking
from src.analysis import tracking_summary as tracking_summary_mod
from src.analysis.scoring import calculator
from src.browser import session as browser_session
from src.models import analysis, consent, tracking_data
from src.models import report as report_models
from src.pipeline import sse_helpers
from src.utils import logger
from src.utils import url as url_mod

log = logger.create_logger("Analysis")


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
            domain = url_mod.extract_domain(url)
            result = await scripts.analyze_scripts(final_scripts, _script_progress, domain=domain)
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


def _render_report_text(
    url: str,
    score: int,
    score_summary: str,
    summary_findings: list[analysis.SummaryFinding],
    report: report_models.StructuredReport,
) -> str:
    """Render the structured report as a plain-text file.

    Produces a human-readable text version of the complete
    analysis for archival purposes.
    """
    lines: list[str] = [
        "=" * 72,
        f"  Privacy Analysis Report — {url}",
        "=" * 72,
        "",
        f"Privacy Score: {score}/100",
        score_summary,
        "",
    ]

    # Summary findings
    if summary_findings:
        lines.append("─" * 40)
        lines.append("SUMMARY")
        lines.append("─" * 40)
        for f in summary_findings:
            lines.append(f"  [{f.type.upper()}] {f.text}")
        lines.append("")

    # Privacy risk
    risk = report.privacy_risk
    if risk.summary:
        lines.append("─" * 40)
        lines.append(f"PRIVACY RISK ASSESSMENT — {risk.overall_risk.upper()}")
        lines.append("─" * 40)
        lines.append(risk.summary)
        for rf in risk.factors:
            lines.append(f"  [{rf.severity.upper()}] {rf.description}")
        lines.append("")

    # Tracking technologies
    tech = report.tracking_technologies
    all_trackers = tech.analytics + tech.advertising + tech.identity_resolution + tech.social_media + tech.other
    if all_trackers:
        lines.append("─" * 40)
        lines.append("TRACKING TECHNOLOGIES")
        lines.append("─" * 40)
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

    # Data collection
    if report.data_collection.items:
        lines.append("─" * 40)
        lines.append("DATA COLLECTION")
        lines.append("─" * 40)
        for item in report.data_collection.items:
            sens = " [SENSITIVE]" if item.sensitive else ""
            lines.append(f"  {item.category} ({item.risk}){sens}")
            for d in item.details:
                lines.append(f"    - {d}")
            if item.shared_with:
                lines.append(f"    Shared with: {', '.join(item.shared_with)}")
        lines.append("")

    # Third-party services
    tp = report.third_party_services
    if tp.groups:
        lines.append("─" * 40)
        lines.append(f"THIRD-PARTY SERVICES ({tp.total_domains} domains)")
        lines.append("─" * 40)
        for tpg in tp.groups:
            lines.append(f"  {tpg.category}: {', '.join(tpg.services)}")
            lines.append(f"    Impact: {tpg.privacy_impact}")
        if tp.summary:
            lines.append(f"\n  {tp.summary}")
        lines.append("")

    # Cookie analysis
    cookie_sec = report.cookie_analysis
    if cookie_sec.groups:
        lines.append("─" * 40)
        lines.append(f"COOKIE ANALYSIS ({cookie_sec.total} cookies)")
        lines.append("─" * 40)
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

    # Storage analysis
    sa = report.storage_analysis
    if sa.local_storage_count or sa.session_storage_count:
        lines.append("─" * 40)
        lines.append("STORAGE ANALYSIS")
        lines.append("─" * 40)
        lines.append(f"  localStorage: {sa.local_storage_count} items")
        lines.append(f"  sessionStorage: {sa.session_storage_count} items")
        for concern in sa.local_storage_concerns:
            lines.append(f"    [localStorage] {concern}")
        for concern in sa.session_storage_concerns:
            lines.append(f"    [sessionStorage] {concern}")
        if sa.summary:
            lines.append(f"\n  {sa.summary}")
        lines.append("")

    # Consent analysis
    consent_sec = report.consent_analysis
    if consent_sec.has_consent_dialog or consent_sec.discrepancies:
        lines.append("─" * 40)
        lines.append("CONSENT ANALYSIS")
        lines.append("─" * 40)
        lines.append(f"  Consent dialog: {'Yes' if consent_sec.has_consent_dialog else 'No'}")
        if consent_sec.categories_disclosed:
            lines.append(f"  Categories disclosed: {consent_sec.categories_disclosed}")
        if consent_sec.partners_disclosed:
            lines.append(f"  Partners disclosed: {consent_sec.partners_disclosed}")
        for disc in consent_sec.discrepancies:
            lines.append(f"  [{disc.severity.upper()}] Claimed: {disc.claimed}")
            lines.append(f"    Actual: {disc.actual}")
        if consent_sec.summary:
            lines.append(f"\n  {consent_sec.summary}")
        lines.append("")

    # Key vendors
    if report.key_vendors.vendors:
        lines.append("─" * 40)
        lines.append("TOP VENDORS AND PARTNERS")
        lines.append("─" * 40)
        for v in report.key_vendors.vendors:
            if v.url:
                lines.append(f"  • {v.name} ({v.role}) — {v.url}")
            else:
                lines.append(f"  • {v.name} ({v.role})")
            lines.append(f"    {v.privacy_impact}")
        lines.append("")

    # Recommendations
    if report.recommendations.groups:
        lines.append("─" * 40)
        lines.append("RECOMMENDATIONS")
        lines.append("─" * 40)
        for rg in report.recommendations.groups:
            lines.append(f"\n  {rg.category}:")
            for rec in rg.items:
                lines.append(f"    • {rec}")
        lines.append("")

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

    yield sse_helpers.format_progress_event("ai-report", "Building report...", 97)

    structured_report, summary_findings = await asyncio.gather(structured_report_task, summary_task)
    log.info(
        "Structured report and summary generated",
        {"summaryCount": len(summary_findings)},
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
        )
        logger.save_report_file(domain, report_text)

        # Persist domain knowledge for future consistency.
        domain_cache.save_from_report(domain, structured_report)

    # ── Build final payload ─────────────────────────────────

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

    yield sse_helpers.format_progress_event("complete", "Investigation complete!", 100)

    yield sse_helpers.format_sse_event(
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
                    "domainBreakdown": [sse_helpers.to_camel_case_dict(d) for d in tracking_summary.domain_breakdown],
                    "localStorage": tracking_summary.local_storage,
                    "sessionStorage": tracking_summary.session_storage,
                }
                if tracking_summary
                else None
            ),
            "analysisError": (None if analysis_success else "Analysis produced no output"),
            "consentDetails": consent_dict,
            "scripts": [sse_helpers.to_camel_case_dict(s) for s in script_result.scripts],
            "scriptGroups": [sse_helpers.to_camel_case_dict(g) for g in script_result.groups],
            "debugLog": logger.get_log_buffer(),
        },
    )
