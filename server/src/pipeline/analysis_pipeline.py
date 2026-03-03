"""
AI analysis pipeline — maximum-concurrency agent orchestration.

Pre-computes deterministic values (scoring, tracking summary,
domain knowledge) then launches three concurrent work-streams:

1. Script grouping/identification (with semaphore-bounded LLM)
2. Streaming LLM tracking analysis
3. Structured report generation (10 LLM sections in parallel)

Once the tracking stream finishes, the summary-findings agent
runs concurrently with any still-in-flight report sections.
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
_MAX_SCRIPTS = 200
_MAX_SCRIPT_GROUPS = 100

# Human-readable labels for report section progress events.
_SECTION_LABELS: dict[str, str] = {
    "tracking-technologies": "Tracking technologies",
    "data-collection": "Data collection",
    "third-party-services": "Third-party services",
    "cookie-analysis": "Cookie analysis",
    "storage-analysis": "Storage analysis",
    "privacy-risk": "Privacy risk",
    "consent-analysis": "Consent analysis",
    "social-media-implications": "Social media",
    "recommendations": "Recommendations",
}


async def run_ai_analysis(
    session: browser_session.BrowserSession,
    storage: tracking_data.CapturedStorage,
    url: str,
    consent_details: consent.ConsentDetails | None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
    *,
    decoded_cookies: dict[str, object] | None = None,
) -> AsyncGenerator[str]:
    """Run script and tracking analysis concurrently.

    Streams SSE events (progress + analysis chunks) as they
    become available, then yields scoring, summary, and the
    final ``complete`` event.
    """
    # Capture the latest cookies and storage from the browser
    # context.  Earlier phases capture at specific checkpoints
    # (initial load, after overlay click) but deferred scripts
    # and post-consent tracking may have added more since then.
    yield sse_helpers.format_progress_event(
        "final-capture",
        "Capturing final page state...",
        75,
    )
    await session.capture_current_cookies()
    storage = await session.capture_storage()

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
            "localStorage": len(storage.local_storage),
            "sessionStorage": len(storage.session_storage),
        },
    )
    yield sse_helpers.format_progress_event(
        "analysis-start",
        "Starting analysis...",
        76,
    )

    log.info("Starting AI analysis")
    log.start_timer("ai-analysis")

    # ── Pre-compute deterministic values ──────────────────────
    # Scoring and the structured report only depend on raw
    # captured data, not on LLM analysis output.  Computing
    # them upfront lets us start the structured report
    # concurrently with script and tracking analysis.
    tracking_summary = tracking_summary_mod.build_tracking_summary(
        final_cookies,
        final_scripts,
        final_requests,
        storage.local_storage,
        storage.session_storage,
        url,
    )

    score_breakdown = calculator.calculate_privacy_score(
        final_cookies,
        final_scripts,
        final_requests,
        storage.local_storage,
        storage.session_storage,
        url,
        consent_details,
        pre_consent_stats,
    )
    log.info(
        "Privacy score calculated",
        {"score": score_breakdown.total_score},
    )

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

    # ── Launch concurrent tasks and yield events in real-time ──
    progress_queue: asyncio.Queue[str | None] = asyncio.Queue()

    script_task, tracking_task = _launch_concurrent_tasks(
        progress_queue,
        final_cookies,
        final_scripts,
        final_requests,
        storage,
        url,
        consent_details,
        pre_consent_stats,
        tracking_summary=tracking_summary,
        score_breakdown=score_breakdown,
        domain_knowledge=domain_knowledge,
    )

    # Start the structured report concurrently with script
    # and tracking analysis — it depends only on the
    # pre-computed deterministic values above.  Section
    # progress is pushed onto the same queue so the client
    # sees granular updates as each report section finishes.
    def _report_section_done(section_name: str, done: int, total: int) -> None:
        label = _SECTION_LABELS.get(section_name, section_name)
        log.info(f"Report section complete: {label} ({done}/{total})")
        progress_queue.put_nowait(
            sse_helpers.format_progress_event(
                "report-section",
                f"Generating report: {label}...",
                90 + int((done / total) * 4),  # 90-94
            )
        )

    report_agent = agents.get_structured_report_agent()

    async def _run_report() -> report_models.StructuredReport:
        try:
            return await report_agent.build_report(
                tracking_summary,
                consent_details,
                pre_consent_stats,
                score_breakdown,
                domain_knowledge,
                on_section_done=_report_section_done,
            )
        finally:
            progress_queue.put_nowait(None)

    report_task = asyncio.create_task(_run_report())

    # Drain events as they arrive — this keeps SSE streaming
    # in real-time rather than batching.  Three concurrent
    # producers (script, tracking, report) each send a None
    # sentinel when they finish.
    tasks_remaining = 3
    finished = 0
    while finished < tasks_remaining:
        event = await progress_queue.get()
        if event is None:
            finished += 1
            continue
        yield event

    try:
        await script_task
        await tracking_task
        await report_task
    except Exception:
        # Cancel surviving tasks so they don't leak.
        for task in (script_task, tracking_task, report_task):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        raise

    script_result = script_task.result()
    analysis_result = tracking_task.result()

    log.end_timer("tracking-analysis", "Tracking analysis complete")

    log.info("Finalizing privacy score", {"score": score_breakdown.total_score})
    yield sse_helpers.format_progress_event("ai-scoring", "Finalizing privacy score...", 95)

    # ── Summary (scoring + report already in flight) ────────
    async for event in _score_and_summarise(
        final_cookies,
        final_requests,
        storage,
        url,
        consent_details,
        analysis_result,
        script_result,
        tracking_summary,
        score_breakdown,
        domain_knowledge,
        report_task,
        pre_consent_stats,
        decoded_cookies=decoded_cookies,
    ):
        yield event


def _launch_concurrent_tasks(
    progress_queue: asyncio.Queue[str | None],
    final_cookies: list[tracking_data.TrackedCookie],
    final_scripts: list[tracking_data.TrackedScript],
    final_requests: list[tracking_data.NetworkRequest],
    storage: tracking_data.CapturedStorage,
    url: str,
    consent_details: consent.ConsentDetails | None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
    tracking_summary: analysis.TrackingSummary | None = None,
    score_breakdown: analysis.ScoreBreakdown | None = None,
    domain_knowledge: domain_cache.DomainKnowledge | None = None,
) -> tuple[asyncio.Task[scripts.ScriptAnalysisResult], asyncio.Task[analysis.TrackingAnalysisResult]]:
    """Create and launch the concurrent script + tracking tasks.

    Both tasks push ``None`` sentinels onto *progress_queue*
    when they finish.  The caller is responsible for draining
    the queue to keep events streaming in real-time.

    Args:
        tracking_summary: Optional pre-built tracking summary
            passed through to the tracking analysis to avoid
            rebuilding it.
        score_breakdown: Deterministic privacy score so the
            LLM can calibrate its risk assessment.
        domain_knowledge: Prior-run classifications for
            consistency anchoring.

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
                        "Identifying known scripts...",
                        77,
                    )
                )
        elif phase == "fetching":
            pct = 77 + int((current / max(total, 1)) * 2)
            progress_queue.put_nowait(
                sse_helpers.format_progress_event(
                    "script-fetching",
                    "Fetching script contents...",
                    pct,
                )
            )
        elif phase == "analyzing":
            if total == 0:
                progress_queue.put_nowait(
                    sse_helpers.format_progress_event(
                        "script-analysis",
                        "All scripts identified from known patterns",
                        82,
                    )
                )
            else:
                pct = min(79 + int((current / total) * 11), 89)
                progress_queue.put_nowait(
                    sse_helpers.format_progress_event(
                        "script-analysis",
                        "Analyzing scripts...",
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

    async def _run_tracking() -> analysis.TrackingAnalysisResult:
        try:
            return await tracking.run_tracking_analysis(
                final_cookies,
                storage.local_storage,
                storage.session_storage,
                final_requests,
                final_scripts,
                url,
                consent_details,
                pre_consent_stats,
                tracking_summary=tracking_summary,
                score_breakdown=score_breakdown,
                domain_knowledge=domain_knowledge,
            )
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


def _render_tc_string_data(
    consent_details: consent.ConsentDetails | None,
) -> list[str]:
    """Render the decoded TC String section."""
    if not consent_details or not consent_details.tc_string_data:
        return []
    tc = consent_details.tc_string_data
    lines = [_SECTION_DIVIDER, "TC STRING (euconsent-v2)", _SECTION_DIVIDER]
    lines.append(f"  Version:                {tc.get('version', '?')}")
    lines.append(f"  CMP ID:                 {tc.get('cmpId', '?')}")
    lines.append(f"  CMP version:            {tc.get('cmpVersion', '?')}")
    lines.append(f"  Consent language:       {tc.get('consentLanguage', '?')}")
    lines.append(f"  Vendor list version:    {tc.get('vendorListVersion', '?')}")
    lines.append(f"  Publisher country:      {tc.get('publisherCountryCode', '?')}")
    lines.append(f"  Service-specific:       {tc.get('isServiceSpecific', '?')}")
    lines.append(f"  Created:                {tc.get('created', '?')}")
    lines.append(f"  Last updated:           {tc.get('lastUpdated', '?')}")
    purposes = tc.get("purposeConsents", [])
    if purposes:
        lines.append(f"  Purpose consents:       {purposes}")
    li_purposes = tc.get("purposeLegitimateInterests", [])
    if li_purposes:
        lines.append(f"  Purpose LI:             {li_purposes}")
    special = tc.get("specialFeatureOptIns", [])
    if special:
        lines.append(f"  Special feature opt-ins: {special}")
    lines.append(f"  Vendor consents:        {tc.get('vendorConsentCount', 0)}")
    lines.append(f"  Vendor LI:              {tc.get('vendorLiCount', 0)}")
    lines.append("")
    return lines


def _render_ac_string_data(
    consent_details: consent.ConsentDetails | None,
) -> list[str]:
    """Render the decoded AC String section."""
    if not consent_details or not consent_details.ac_string_data:
        return []
    ac = consent_details.ac_string_data
    lines = [_SECTION_DIVIDER, "AC STRING (addtl_consent)", _SECTION_DIVIDER]
    lines.append(f"  Version:            {ac.get('version', '?')}")
    lines.append(f"  Vendor count:       {ac.get('vendorCount', 0)}")
    unresolved = ac.get("unresolvedProviderCount", 0)
    resolved = list(ac.get("resolvedProviders", []))  # type: ignore[call-overload]
    if resolved:
        lines.append(f"  Resolved providers: {len(resolved)}")
        for p in resolved[:20]:
            name = p.get("name", str(p.get("id", "?")))  # type: ignore[union-attr]
            lines.append(f"    • {name}")
        if len(resolved) > 20:
            lines.append(f"    ... and {len(resolved) - 20} more")
    if unresolved:
        lines.append(f"  Unresolved IDs:     {unresolved}")
    lines.append("")
    return lines


def _render_tc_validation(
    consent_details: consent.ConsentDetails | None,
) -> list[str]:
    """Render the TC validation findings section."""
    if not consent_details or not consent_details.tc_validation:
        return []
    val = consent_details.tc_validation
    findings: list[dict[str, object]] = val.get("findings", [])  # type: ignore[assignment]
    special: list[str] = val.get("specialFeatures", [])  # type: ignore[assignment]
    mismatch = val.get("vendorCountMismatch", False)
    if not findings and not special and not mismatch:
        return []
    lines = [_SECTION_DIVIDER, "TC VALIDATION", _SECTION_DIVIDER]
    v_consent = val.get("vendorConsentCount", 0)
    v_li = val.get("vendorLiCount", 0)
    claimed = val.get("claimedPartnerCount")
    lines.append(f"  Vendor consents: {v_consent}  |  Vendor LI: {v_li}")
    if claimed is not None:
        lines.append(f"  Claimed partner count: {claimed}")
    if mismatch:
        lines.append("  ⚠ Vendor count mismatch between dialog and TC String")
    if special:
        lines.append(f"  Special features: {', '.join(special)}")
    if findings:
        lines.append("")
        lines.append("  Findings:")
        for f in findings:
            sev = str(f.get("severity", "?")).upper()
            title = f.get("title", "")
            detail = f.get("detail", "")
            lines.append(f"    [{sev}] {title}")
            if detail:
                lines.append(f"      {detail}")
    lines.append("")
    return lines


def _render_decoded_cookies(
    decoded_cookies: dict[str, object] | None,
) -> list[str]:
    """Render the decoded privacy cookies section."""
    if not decoded_cookies:
        return []
    lines = [_SECTION_DIVIDER, "DECODED PRIVACY COOKIES", _SECTION_DIVIDER]

    usp = decoded_cookies.get("uspString")
    if isinstance(usp, dict):
        lines.append(f"  USP String: {usp.get('rawString', '?')}")
        lines.append(f"    Notice given: {usp.get('noticeLabel', '?')}")
        lines.append(f"    Opted out:    {usp.get('optOutLabel', '?')}")
        lines.append(f"    LSPA:         {usp.get('lspaLabel', '?')}")

    gpp = decoded_cookies.get("gppString")
    if isinstance(gpp, dict):
        sections = gpp.get("sections", [])
        section_names = [s.get("name", str(s.get("id"))) for s in sections] if isinstance(sections, list) else []  # type: ignore[union-attr]
        lines.append(f"  GPP String: {gpp.get('rawString', '?')[:80]}")
        lines.append(f"    Segments: {gpp.get('segmentCount', '?')}")
        if section_names:
            lines.append(f"    Sections: {', '.join(section_names)}")

    ga = decoded_cookies.get("googleAnalytics")
    if isinstance(ga, dict):
        lines.append(f"  Google Analytics (_ga): {ga.get('clientId', '?')}")
        lines.append(f"    First visit: {ga.get('firstVisit', '?')}")

    fb = decoded_cookies.get("facebookPixel")
    if isinstance(fb, dict):
        fbp = fb.get("fbp")
        fbc = fb.get("fbc")
        if isinstance(fbp, dict):
            lines.append(f"  Facebook _fbp: browser {fbp.get('browserId', '?')}")
            lines.append(f"    Created: {fbp.get('created', '?')}")
        if isinstance(fbc, dict):
            lines.append(f"  Facebook _fbc: click {fbc.get('fbclid', '?')[:30]}...")
            lines.append(f"    Clicked: {fbc.get('clicked', '?')}")

    gads = decoded_cookies.get("googleAds")
    if isinstance(gads, dict):
        gau = gads.get("gclAu")
        gaw = gads.get("gclAw")
        if isinstance(gau, dict):
            lines.append(f"  Google Ads _gcl_au: v{gau.get('version', '?')}")
            lines.append(f"    Created: {gau.get('created', '?')}")
        if isinstance(gaw, dict):
            lines.append(f"  Google Ads _gcl_aw: {gaw.get('gclid', '?')[:30]}...")
            lines.append(f"    Clicked: {gaw.get('clicked', '?')}")

    ot = decoded_cookies.get("oneTrust")
    if isinstance(ot, dict):
        cats = ot.get("categories", [])
        lines.append("  OneTrust (OptanonConsent):")
        if isinstance(cats, list):
            for c in cats:
                if isinstance(c, dict):
                    status = "✓" if c.get("consented") else "✗"
                    lines.append(f"    {status} {c.get('name', c.get('id', '?'))}")
        if ot.get("isGpcApplied"):
            lines.append("    GPC signal applied")

    cb = decoded_cookies.get("cookiebot")
    if isinstance(cb, dict):
        cats = cb.get("categories", [])
        lines.append("  Cookiebot (CookieConsent):")
        if isinstance(cats, list):
            for c in cats:
                if isinstance(c, dict):
                    status = "✓" if c.get("consented") else "✗"
                    lines.append(f"    {status} {c.get('name', '?')}")

    socs = decoded_cookies.get("googleSocs")
    if isinstance(socs, dict):
        lines.append(f"  Google SOCS: {socs.get('consentMode', '?')}")

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
    decoded_cookies: dict[str, object] | None = None,
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
    lines += _render_tc_string_data(consent_details)
    lines += _render_ac_string_data(consent_details)
    lines += _render_tc_validation(consent_details)
    lines += _render_decoded_cookies(decoded_cookies)
    lines += _render_recommendations(report)
    lines += _render_llm_usage()
    lines.append("=" * 72)
    return "\n".join(lines)


async def _score_and_summarise(
    final_cookies: list[tracking_data.TrackedCookie],
    final_requests: list[tracking_data.NetworkRequest],
    storage: tracking_data.CapturedStorage,
    url: str,
    consent_details: consent.ConsentDetails | None,
    analysis_result: analysis.TrackingAnalysisResult,
    script_result: scripts.ScriptAnalysisResult,
    tracking_summary: analysis.TrackingSummary,
    score_breakdown: analysis.ScoreBreakdown,
    domain_knowledge: domain_cache.DomainKnowledge | None,
    report_task: asyncio.Task[report_models.StructuredReport],
    pre_consent_stats: analysis.PreConsentStats | None = None,
    *,
    decoded_cookies: dict[str, object] | None = None,
) -> AsyncGenerator[str]:
    """Summarise and yield the complete event.

    Scoring, the tracking summary, domain knowledge, and the
    structured report are pre-computed / pre-launched by the
    caller for maximum concurrency.
    """
    full_text = analysis_result.to_text()
    log.info("Analysis complete", {"length": len(full_text)})

    # The structured report is already being built concurrently
    # (launched alongside script and tracking analysis).  Only
    # the summary needs the completed analysis text.
    log.info("Generating findings summary")
    yield sse_helpers.format_progress_event("ai-summarizing", "Generating findings summary...", 96)

    summary_agent = agents.get_summary_findings_agent()
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

    try:
        structured_report, summary_findings = await asyncio.gather(
            report_task,
            summary_task,
        )
    except Exception:
        # Cancel the surviving task so it doesn't leak.
        for task in (report_task, summary_task):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        raise

    log.info(
        "Structured report and summary generated",
        {"summaryCount": len(summary_findings)},
    )
    yield sse_helpers.format_progress_event("ai-report", "Finalizing report...", 98)

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
    domain = url_mod.extract_domain(url)
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
            decoded_cookies=decoded_cookies,
        )
        logger.save_report_file(domain, report_text)

        # Persist domain knowledge for future consistency.
        domain_cache.save_from_report(domain, structured_report)

    # ── Build final payload ─────────────────────────────────

    log.success("Investigation complete")
    yield sse_helpers.format_progress_event("complete", "Investigation complete!", 100)

    yield _build_complete_payload(
        structured_report,
        summary_findings,
        score_breakdown,
        consent_details,
        script_result,
        analysis_success=bool(full_text),
        final_cookies=final_cookies,
        final_requests=final_requests,
        storage=storage,
        decoded_cookies=decoded_cookies,
    )


def _build_complete_payload(
    structured_report: report_models.StructuredReport | None,
    summary_findings: list[analysis.SummaryFinding],
    score_breakdown: analysis.ScoreBreakdown,
    consent_details: consent.ConsentDetails | None,
    script_result: scripts.ScriptAnalysisResult,
    analysis_success: bool = True,
    final_cookies: list[tracking_data.TrackedCookie] | None = None,
    final_requests: list[tracking_data.NetworkRequest] | None = None,
    storage: tracking_data.CapturedStorage | None = None,
    decoded_cookies: dict[str, object] | None = None,
) -> str:
    """Build the final SSE ``complete`` event payload.

    Large collections (scripts, groups) are capped to prevent
    multi-MB SSE events on sites with hundreds of third-party
    scripts.
    """
    privacy_score = score_breakdown.total_score

    if analysis_success:
        log.success(
            "Analysis succeeded",
            {"privacyScore": privacy_score},
        )
    else:
        log.error("Analysis produced no output")

    consent_dict = sse_helpers.serialize_consent_details(consent_details) if consent_details else None

    return sse_helpers.format_sse_event(
        "complete",
        {
            "message": "Investigation complete!",
            "structuredReport": (structured_report.model_dump(by_alias=True) if analysis_success and structured_report else None),
            "summaryFindings": ([{"type": f.type, "text": f.text} for f in summary_findings] if analysis_success else None),
            "privacyScore": (privacy_score if analysis_success else None),
            "privacySummary": (score_breakdown.summary if analysis_success else None),
            "analysisError": (None if analysis_success else "Analysis produced no output"),
            "consentDetails": consent_dict,
            "decodedCookies": decoded_cookies,
            "cookies": [sse_helpers.to_camel_case_dict(c) for c in final_cookies] if final_cookies is not None else None,
            "networkRequests": ([sse_helpers.to_camel_case_dict(r) for r in final_requests] if final_requests is not None else None),
            "localStorage": ([sse_helpers.to_camel_case_dict(i) for i in storage.local_storage] if storage else None),
            "sessionStorage": ([sse_helpers.to_camel_case_dict(i) for i in storage.session_storage] if storage else None),
            "scripts": [sse_helpers.to_camel_case_dict(s) for s in script_result.scripts[:_MAX_SCRIPTS]],
            "scriptGroups": [sse_helpers.to_camel_case_dict(g) for g in script_result.groups[:_MAX_SCRIPT_GROUPS]],
            "debugLog": logger.get_log_buffer(),
        },
    )
