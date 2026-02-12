"""
AI analysis pipeline — concurrent script + tracking analysis.

Runs script grouping/identification and LLM tracking analysis in
parallel, then scores results and generates summary findings.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator

from src import agents
from src.analysis import scripts, tracking
from src.analysis import privacy_score as privacy_score_mod
from src.analysis import tracking_summary as tracking_summary_mod
from src.browser import session as browser_session
from src.models import consent, tracking_data
from src.pipeline import sse_helpers
from src.utils import logger

log = logger.create_logger("Analysis")


async def run_ai_analysis(
    session: browser_session.BrowserSession,
    storage: dict[str, list[tracking_data.StorageItem]],
    url: str,
    consent_details: consent.ConsentDetails | None,
    overlay_count: int = 0,
) -> AsyncGenerator[str, None]:
    """Run script and tracking analysis concurrently.

    Streams SSE events (progress + analysis chunks) as they
    become available, then yields scoring, summary, and the
    final ``complete`` event.
    """
    final_cookies = session.get_tracked_cookies()
    final_scripts = session.get_tracked_scripts()
    final_requests = session.get_tracked_network_requests()

    log.info(
        "Final data stats",
        {
            "cookies": len(final_cookies),
            "scripts": len(final_scripts),
            "requests": len(final_requests),
        },
    )
    yield sse_helpers.format_progress_event(
        "analysis-start",
        "Starting analysis...",
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
    ):
        yield event


def _launch_concurrent_tasks(
    progress_queue: asyncio.Queue[str | None],
    final_cookies: list,
    final_scripts: list,
    final_requests: list,
    storage: dict[str, list[tracking_data.StorageItem]],
    url: str,
    consent_details: consent.ConsentDetails | None,
    analysis_chunks: list[str],
) -> tuple[asyncio.Task, asyncio.Task]:
    """Create and launch the concurrent script + tracking tasks.

    Both tasks push SSE event strings (or ``None`` sentinels) onto
    *progress_queue*.  The caller is responsible for draining the
    queue to keep events streaming in real-time.

    Returns:
        Tuple of (script_task, tracking_task).
    """
    log.start_timer("script-analysis")

    def _script_progress(
        phase: str, current: int, total: int, detail: str
    ) -> None:
        log.info(
            f"Script analysis progress: {phase}"
            f" {current}/{total} - {detail}"
        )
        if phase == "matching":
            if current == 0:
                progress_queue.put_nowait(
                    sse_helpers.format_progress_event(
                        "script-matching",
                        detail
                        or "Grouping and identifying scripts...",
                        77,
                    )
                )
        elif phase == "fetching":
            pct = 77 + int((current / max(total, 1)) * 2)
            progress_queue.put_nowait(
                sse_helpers.format_progress_event(
                    "script-fetching",
                    detail
                    or f"Fetching script {current}/{total}...",
                    pct,
                )
            )
        elif phase == "analyzing":
            if total == 0:
                progress_queue.put_nowait(
                    sse_helpers.format_progress_event(
                        "script-analysis",
                        detail or "All scripts identified...",
                        82,
                    )
                )
            else:
                pct = 79 + int((current / total) * 11)
                progress_queue.put_nowait(
                    sse_helpers.format_progress_event(
                        "script-analysis",
                        detail
                        or f"Analyzed {current}/{total}"
                        f" scripts...",
                        pct,
                    )
                )

    async def _run_scripts() -> Any:
        try:
            result = await scripts.analyze_scripts(
                final_scripts, _script_progress
            )
            log.end_timer(
                "script-analysis",
                f"Script analysis complete..."
                f" ({len(result.scripts)} scripts,"
                f" {len(result.groups)} groups)",
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
            ):
                analysis_chunks.append(chunk)
                progress_queue.put_nowait(
                    sse_helpers.format_sse_event(
                        "analysis-chunk", {"text": chunk}
                    )
                )
        finally:
            progress_queue.put_nowait(None)

    script_task = asyncio.create_task(_run_scripts())
    tracking_task = asyncio.create_task(_run_tracking())

    return script_task, tracking_task


async def _score_and_summarise(
    final_cookies: list,
    final_scripts: list,
    final_requests: list,
    storage: dict[str, list[tracking_data.StorageItem]],
    url: str,
    consent_details: consent.ConsentDetails | None,
    overlay_count: int,
    analysis_chunks: list[str],
    script_result: Any,
) -> AsyncGenerator[str, None]:
    """Score, summarise, and yield the complete event."""
    full_text = "".join(analysis_chunks)
    log.info("Analysis streamed", {"length": len(full_text)})

    yield sse_helpers.format_progress_event(
        "ai-scoring", "Calculating privacy score...", 94
    )

    tracking_summary = tracking_summary_mod.build_tracking_summary(
        final_cookies,
        final_scripts,
        final_requests,
        storage["local_storage"],
        storage["session_storage"],
        url,
    )

    score_breakdown = privacy_score_mod.calculate_privacy_score(
        final_cookies,
        final_scripts,
        final_requests,
        storage["local_storage"],
        storage["session_storage"],
        url,
        consent_details,
    )

    yield sse_helpers.format_progress_event(
        "ai-summarizing", "Generating summary findings...", 97
    )
    summary_agent = agents.get_summary_findings_agent()
    summary_findings = await summary_agent.summarise(full_text)
    log.info("Summary findings generated", {"count": len(summary_findings)})

    log.end_timer("ai-analysis", "All AI analysis complete")

    # ── Build final payload ─────────────────────────────────
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

    consent_dict = (
        sse_helpers.serialize_consent_details(consent_details)
        if consent_details
        else None
    )
    score_dict = (
        sse_helpers.serialize_score_breakdown(score_breakdown)
        if score_breakdown
        else None
    )

    yield sse_helpers.format_progress_event(
        "complete", "Investigation complete!", 100
    )

    yield sse_helpers.format_sse_event(
        "complete",
        {
            "success": True,
            "message": (
                "Tracking analyzed after dismissing overlays"
                if overlay_count > 0
                else "Tracking analyzed"
            ),
            "analysis": full_text if analysis_success else None,
            "summaryFindings": (
                [
                    {"type": f.type, "text": f.text}
                    for f in summary_findings
                ]
                if analysis_success
                else None
            ),
            "privacyScore": (
                privacy_score if analysis_success else None
            ),
            "privacySummary": (
                score_breakdown.summary
                if analysis_success
                else None
            ),
            "scoreBreakdown": (
                score_dict if analysis_success else None
            ),
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
                        sse_helpers.to_camel_case_dict(d)
                        for d in tracking_summary.domain_breakdown
                    ],
                    "localStorage": tracking_summary.local_storage,
                    "sessionStorage": tracking_summary.session_storage,
                }
                if tracking_summary
                else None
            ),
            "analysisError": (
                None
                if analysis_success
                else "Analysis produced no output"
            ),
            "consentDetails": consent_dict,
            "scripts": [
                sse_helpers.to_camel_case_dict(s)
                for s in script_result.scripts
            ],
            "scriptGroups": [
                sse_helpers.to_camel_case_dict(g)
                for g in script_result.groups
            ],
        },
    )
