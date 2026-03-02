"""AI-powered tracking analysis service.

Orchestrates the ``TrackingAnalysisAgent`` to produce a
structured privacy analysis.  Scoring and summary findings
are handled separately by the caller.
"""

from __future__ import annotations

from src import agents
from src.analysis import domain_cache
from src.analysis import tracking_summary as tracking_summary_mod
from src.models import analysis, consent, tracking_data
from src.utils import logger

log = logger.create_logger("AI-Analysis")


async def run_tracking_analysis(
    cookies: list[tracking_data.TrackedCookie],
    local_storage: list[tracking_data.StorageItem],
    session_storage: list[tracking_data.StorageItem],
    network_requests: list[tracking_data.NetworkRequest],
    scripts: list[tracking_data.TrackedScript],
    analyzed_url: str,
    consent_details: consent.ConsentDetails | None = None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
    tracking_summary: analysis.TrackingSummary | None = None,
    score_breakdown: analysis.ScoreBreakdown | None = None,
    domain_knowledge: domain_cache.DomainKnowledge | None = None,
) -> analysis.TrackingAnalysisResult:
    """Run the main tracking analysis and return structured output.

    Delegates to ``TrackingAnalysisAgent.analyze()`` which
    uses structured JSON output via ``response_format``.

    Args:
        cookies: Tracked cookies from the page.
        local_storage: localStorage items.
        session_storage: sessionStorage items.
        network_requests: Captured network requests.
        scripts: Tracked scripts.
        analyzed_url: The URL that was analysed.
        consent_details: Optional consent dialog info.
        pre_consent_stats: Optional pre-consent page-load stats.
        tracking_summary: Optional pre-built tracking summary.
            When provided, avoids rebuilding the summary
            from the raw data.
        score_breakdown: Deterministic privacy score so the
            LLM can calibrate its risk assessment.
        domain_knowledge: Prior-run classifications for
            consistency anchoring.

    Returns:
        Structured ``TrackingAnalysisResult``.
    """
    log.info(
        "Starting tracking analysis",
        {
            "url": analyzed_url,
            "cookies": len(cookies),
            "scripts": len(scripts),
            "requests": len(network_requests),
            "localStorage": len(local_storage),
            "sessionStorage": len(session_storage),
            "hasConsent": consent_details is not None,
        },
    )
    tracking_agent = agents.get_tracking_analysis_agent()

    if tracking_summary is None:
        tracking_summary = tracking_summary_mod.build_tracking_summary(
            cookies,
            scripts,
            network_requests,
            local_storage,
            session_storage,
            analyzed_url,
        )
    log.debug(
        "Tracking summary built",
        {
            "thirdPartyDomains": len(tracking_summary.third_party_domains),
            "domainBreakdowns": len(tracking_summary.domain_breakdown),
        },
    )

    result = await tracking_agent.analyze(
        tracking_summary,
        consent_details,
        pre_consent_stats,
        score_breakdown,
        domain_knowledge,
    )
    log.info(
        "Tracking analysis complete",
        {
            "riskLevel": result.risk_level,
            "sections": len(result.sections),
        },
    )
    return result
