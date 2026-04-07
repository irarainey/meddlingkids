"""MAF ``@executor`` wrappers for analysis pipeline steps.

Wraps the main analysis pipeline functions as
``FunctionExecutor`` instances via the ``@executor``
decorator, enabling composition via ``WorkflowBuilder``
and providing typed input/output contracts.

These executors are used by the analysis pipeline for
structured, composable orchestration alongside the existing
SSE streaming infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import agent_framework

from src.analysis import scripts, tracking
from src.models import analysis, consent, tracking_data
from src.utils import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.analysis import domain_cache

log = logger.create_logger("PipelineExecutors")


@agent_framework.executor(
    id="script-analysis",
    input=list[tracking_data.TrackedScript],
    output=scripts.ScriptAnalysisResult,
)
async def script_analysis_executor(
    tracked_scripts: list[tracking_data.TrackedScript],
    ctx: agent_framework.WorkflowContext[scripts.ScriptAnalysisResult],
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> None:
    """Execute script analysis on tracked scripts.

    Args:
        tracked_scripts: List of tracked scripts to analyse.
        ctx: Workflow context for sending results.
        progress_callback: Optional progress callback.
    """
    result = await scripts.analyze_scripts(tracked_scripts, progress_callback)
    await ctx.send_message(result)


@agent_framework.executor(
    id="tracking-analysis",
    input=tracking_data.TrackedCookie,
    output=analysis.TrackingAnalysisResult,
)
async def tracking_analysis_executor(
    cookies: list[tracking_data.TrackedCookie],
    ctx: agent_framework.WorkflowContext[analysis.TrackingAnalysisResult],
    local_storage: list[tracking_data.StorageItem] | None = None,
    session_storage: list[tracking_data.StorageItem] | None = None,
    requests: list[tracking_data.NetworkRequest] | None = None,
    tracked_scripts: list[tracking_data.TrackedScript] | None = None,
    url: str = "",
    consent_details: consent.ConsentDetails | None = None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
    tracking_summary: analysis.TrackingSummary | None = None,
    score_breakdown: analysis.ScoreBreakdown | None = None,
    domain_knowledge: domain_cache.DomainKnowledge | None = None,
    decoded_cookies: dict[str, object] | None = None,
) -> None:
    """Execute tracking analysis.

    Args:
        cookies: Tracked cookies from browser session.
        ctx: Workflow context for sending results.
    """
    result = await tracking.run_tracking_analysis(
        cookies,
        local_storage or [],
        session_storage or [],
        requests or [],
        tracked_scripts or [],
        url,
        consent_details,
        pre_consent_stats,
        tracking_summary=tracking_summary,
        score_breakdown=score_breakdown,
        domain_knowledge=domain_knowledge,
        decoded_cookies=decoded_cookies,
    )
    await ctx.send_message(result)
