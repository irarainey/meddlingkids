"""
AI-powered tracking analysis service.

Uses the Microsoft Agent Framework ChatAgent to analyse collected
tracking data and generate comprehensive privacy reports with risk
assessments.  Privacy score is calculated deterministically for
consistency.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from src.agents.chat_agent import get_chat_agent_service
from src.agents.config import (
    AGENT_SUMMARY_FINDINGS,
    AGENT_TRACKING_ANALYSIS,
)
from src.prompts import tracking_analysis
from src.services import privacy_score as privacy_score_mod
from src.types import consent, tracking_data
from src.types import analysis as analysis_mod
from src.utils import errors, logger
from src.utils import tracking_summary as tracking_summary_mod

log = logger.create_logger("AI-Analysis")

# Progress callback type
AnalysisProgressCallback = Callable[[str, str], None]


async def run_tracking_analysis(
    cookies: list[tracking_data.TrackedCookie],
    local_storage: list[tracking_data.StorageItem],
    session_storage: list[tracking_data.StorageItem],
    network_requests: list[tracking_data.NetworkRequest],
    scripts: list[tracking_data.TrackedScript],
    analyzed_url: str,
    consent_details: consent.ConsentDetails | None = None,
    on_progress: AnalysisProgressCallback | None = None,
) -> analysis_mod.AnalysisResult:
    """Run comprehensive tracking analysis using the LLM agent.

    Analyses cookies, scripts, network requests, and storage to
    generate a detailed privacy report and structured summary findings.
    """
    agent_service = get_chat_agent_service()
    if not agent_service.is_configured:
        log.error("LLM agent not configured")
        return analysis_mod.AnalysisResult(
            success=False, error="LLM not configured"
        )

    log.info("Starting tracking analysis", {
        "url": analyzed_url,
        "cookies": len(cookies),
        "scripts": len(scripts),
        "networkRequests": len(network_requests),
    })

    try:
        # Preparing phase
        if on_progress:
            on_progress("preparing", "Building tracking summary...")

        tracking_summary = tracking_summary_mod.build_tracking_summary(
            cookies, scripts, network_requests,
            local_storage, session_storage, analyzed_url,
        )

        # Step 1: Main analysis
        log.start_timer("main-analysis")
        log.info("Running main tracking analysis...")

        if on_progress:
            on_progress("analyzing", "Generating privacy report...")

        analysis = await agent_service.complete(
            system_prompt=tracking_analysis.TRACKING_ANALYSIS_SYSTEM_PROMPT,
            user_prompt=tracking_analysis.build_tracking_analysis_user_prompt(
                tracking_summary, consent_details
            ),
            agent_name=AGENT_TRACKING_ANALYSIS,
            max_tokens=3000,
            retry_context="Main tracking analysis",
        )

        analysis = analysis or "No analysis generated"
        log.end_timer("main-analysis", "Main analysis complete")
        log.info("Analysis generated", {"length": len(analysis)})

        # Step 2: Deterministic privacy score
        log.start_timer("score-calculation")

        if on_progress:
            on_progress("scoring", "Calculating privacy score...")

        score_breakdown = privacy_score_mod.calculate_privacy_score(
            cookies, scripts, network_requests,
            local_storage, session_storage,
            analyzed_url, consent_details,
        )
        log.end_timer("score-calculation", "Privacy score calculated")
        log.info("Privacy score breakdown", {
            "total": score_breakdown.total_score,
            "factors": len(score_breakdown.factors),
        })

        # Step 3: Generate summary findings (LLM-based)
        log.start_timer("summary-generation")
        log.info("Generating summary findings...")

        if on_progress:
            on_progress("summarizing", "Generating summary findings...")

        summary_content: str | None = None
        try:
            summary_content = await agent_service.complete(
                system_prompt=tracking_analysis.SUMMARY_FINDINGS_SYSTEM_PROMPT,
                user_prompt=tracking_analysis.build_summary_findings_user_prompt(
                    analysis
                ),
                agent_name=AGENT_SUMMARY_FINDINGS,
                max_tokens=500,
                retry_context="Summary findings",
            )
            log.end_timer("summary-generation", "Summary generated")
        except Exception as err:
            log.error(
                "Failed to generate summary",
                {"error": errors.get_error_message(err)},
            )

        # Process summary findings
        summary_findings: list[analysis_mod.SummaryFinding] = []
        if summary_content:
            log.debug(
                "Summary findings response",
                {"content": summary_content},
            )
            try:
                json_str = summary_content.strip()
                if json_str.startswith("```"):
                    json_str = re.sub(r"```json?\n?", "", json_str)
                    json_str = re.sub(r"```$", "", json_str).strip()
                raw_findings = json.loads(json_str)
                summary_findings = [
                    analysis_mod.SummaryFinding(
                        type=f.get("type", "info"),
                        text=f.get("text", ""),
                    )
                    for f in raw_findings
                ]
                log.success("Summary findings parsed", {"count": len(summary_findings)})
                for finding in summary_findings:
                    log.info(f"Finding [{finding.type}]: {finding.text}")
            except Exception as parse_error:
                log.error("Failed to parse summary findings JSON", {"error": errors.get_error_message(parse_error)})

        privacy_score = score_breakdown.total_score
        privacy_summary = score_breakdown.summary

        log.info("Privacy score details", {
            "total": privacy_score,
            "cookies": score_breakdown.categories.get("cookies", analysis_mod.CategoryScore()).points,
        })

        log.success("Analysis complete", {
            "findingsCount": len(summary_findings),
            "privacyScore": privacy_score,
            "scoreFactors": score_breakdown.factors[:3],
        })

        return analysis_mod.AnalysisResult(
            success=True,
            analysis=analysis,
            summary_findings=summary_findings,
            privacy_score=privacy_score,
            privacy_summary=privacy_summary,
            score_breakdown=score_breakdown,
            summary=tracking_summary,
        )
    except Exception as error:
        log.error("Analysis failed", {"error": errors.get_error_message(error)})
        return analysis_mod.AnalysisResult(success=False, error=errors.get_error_message(error))
