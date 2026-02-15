"""Summary findings agent for structured privacy findings.

Generates a prioritised list of key privacy findings from
a full tracking analysis using structured JSON output.
"""

from __future__ import annotations

from typing import Literal

import pydantic

from src.agents import base, config
from src.agents.prompts import summary_findings
from src.analysis import domain_cache
from src.models import analysis, consent
from src.utils import json_parsing, logger, risk

log = logger.create_logger("SummaryFindingsAgent")


# ── Structured output models ───────────────────────────────────


class _SummaryFinding(pydantic.BaseModel):
    """A single finding returned by the LLM."""

    type: Literal["critical", "high", "moderate", "info", "positive"]
    text: str


class _SummaryFindingsResponse(pydantic.BaseModel):
    """Schema pushed to the LLM via ``response_format``."""

    findings: list[_SummaryFinding] = pydantic.Field(default_factory=list)


# ── Agent class ─────────────────────────────────────────────────


class SummaryFindingsAgent(base.BaseAgent):
    """Text agent that produces structured summary findings.

    Takes a full privacy analysis and distils it into a
    prioritised list of typed findings.
    """

    agent_name = config.AGENT_SUMMARY_FINDINGS
    instructions = summary_findings.INSTRUCTIONS
    max_tokens = 500
    max_retries = 5
    response_model = _SummaryFindingsResponse

    async def summarise(
        self,
        analysis_text: str,
        score_breakdown: analysis.ScoreBreakdown | None = None,
        domain_knowledge: domain_cache.DomainKnowledge | None = None,
        consent_details: consent.ConsentDetails | None = None,
        tracking_summary: analysis.TrackingSummary | None = None,
        pre_consent_stats: analysis.PreConsentStats | None = None,
    ) -> list[analysis.SummaryFinding]:
        """Generate summary findings from analysis text.

        Args:
            analysis_text: Full markdown privacy analysis.
            score_breakdown: Deterministic privacy score, if
                available, so the LLM can calibrate severity.
            domain_knowledge: Optional cached knowledge from
                a prior analysis of the same domain.
            consent_details: Optional consent dialog info
                (deterministic facts to prevent hallucinated
                partner counts).
            tracking_summary: Optional tracking data summary
                (deterministic metrics like cookie counts,
                domain counts, storage usage).
            pre_consent_stats: Optional pre-consent statistics
                for accurate page-load activity reporting.

        Returns:
            List of typed ``SummaryFinding`` objects.
        """
        log.start_timer("summary-generation")
        log.info("Generating summary findings...")

        score_ctx = ""
        if score_breakdown:
            label = risk.risk_label(score_breakdown.total_score)
            top = ", ".join(score_breakdown.factors[:5]) or "none"
            score_ctx = (
                f"\n\nDeterministic privacy score: "
                f"{score_breakdown.total_score}/100 "
                f"({label}). Top scoring factors: {top}.\n"
                f"Calibrate your severity labels to be "
                f"consistent with this score."
            )

        knowledge_ctx = ""
        if domain_knowledge:
            knowledge_ctx = domain_cache.build_context_hint(
                domain_knowledge,
            )

        consent_ctx = ""
        if consent_details:
            consent_ctx = _build_consent_facts(consent_details)

        metrics_ctx = ""
        if tracking_summary:
            metrics_ctx = _build_metrics_facts(
                tracking_summary,
                pre_consent_stats,
            )

        try:
            response = await self._complete(
                f"Based on this full analysis, create a structured JSON object with key findings:\n\n{analysis_text}{score_ctx}{knowledge_ctx}{consent_ctx}{metrics_ctx}"
            )
            log.end_timer("summary-generation", "Summary generated")

            parsed = self._parse_response(response, _SummaryFindingsResponse)
            if parsed:
                findings = [analysis.SummaryFinding(type=f.type, text=f.text) for f in parsed.findings]
                log.success(
                    "Summary findings parsed",
                    {"count": len(findings)},
                )
                return findings

            # Fallback: manual parse from text
            return _parse_text_fallback(response.text)
        except Exception as err:
            log.error(
                "Failed to generate summary",
                {"error": str(err)},
            )
            return []


# ── Helpers ─────────────────────────────────────────────────────


def _parse_text_fallback(
    text: str | None,
) -> list[analysis.SummaryFinding]:
    """Parse raw LLM text when structured output fails.

    Handles both wrapped ``{"findings": [...]}`` and bare
    ``[...]`` JSON arrays.

    Args:
        text: Raw LLM response text.

    Returns:
        List of ``SummaryFinding`` objects.
    """
    raw = json_parsing.load_json_from_text(text)
    if raw is not None:
        # Support both {"findings": [...]} and [...]
        items = raw.get("findings", raw) if isinstance(raw, dict) else raw
        findings = [
            analysis.SummaryFinding(
                type=f.get("type", "info"),
                text=f.get("text", ""),
            )
            for f in items
            if isinstance(f, dict)
        ]
        log.success(
            "Summary findings parsed (fallback)",
            {"count": len(findings)},
        )
        return findings
    else:
        log.error(
            "Failed to parse summary findings JSON",
            {"text": (text or "")[:200]},
        )
        return []


def _build_consent_facts(
    cd: consent.ConsentDetails,
) -> str:
    """Build deterministic consent facts for the summary prompt.

    Provides the LLM with ground-truth numbers extracted from
    the consent dialog so it doesn't rely on (possibly wrong)
    counts from the streaming analysis text.

    Args:
        cd: Consent details captured from the dialog.

    Returns:
        Formatted context string.
    """
    lines = [
        "",
        "",
        "DETERMINISTIC CONSENT FACTS (use these numbers, do not guess):",
    ]
    if cd.categories:
        lines.append(f"- Consent categories disclosed: {len(cd.categories)}")
    if cd.claimed_partner_count:
        lines.append(f"- Claimed partner count (from dialog text): {cd.claimed_partner_count}")
    if cd.partners:
        lines.append(f"- Individually listed partners extracted: {len(cd.partners)}")
    elif cd.claimed_partner_count:
        lines.append("- Individually listed partners extracted: 0 (dialog states a count but does not list them individually)")
    if cd.purposes:
        lines.append(f"- Stated purposes: {len(cd.purposes)}")
    return "\n".join(lines)


def _build_metrics_facts(
    ts: analysis.TrackingSummary,
    pre_consent: analysis.PreConsentStats | None = None,
) -> str:
    """Build deterministic tracking metrics for the summary prompt.

    Provides the LLM with ground-truth numbers so it uses
    exact counts rather than approximations or hallucinated
    figures from the streaming analysis text.

    Args:
        ts: Tracking data summary with counts and domains.
        pre_consent: Optional pre-consent page-load stats.

    Returns:
        Formatted context string.
    """
    lines = [
        "",
        "",
        "DETERMINISTIC TRACKING METRICS (use these exact numbers, do not guess or approximate):",
        f"- Total cookies: {ts.total_cookies}",
        f"- Total scripts: {ts.total_scripts}",
        f"- Total network requests: {ts.total_network_requests}",
        f"- localStorage items: {ts.local_storage_items}",
        f"- sessionStorage items: {ts.session_storage_items}",
        f"- Third-party domains: {len(ts.third_party_domains)}",
    ]
    if pre_consent:
        lines.extend(
            [
                "",
                "Activity on initial page load (before any dialogs were dismissed):",
                "NOTE: We cannot confirm whether these scripts use the cookies listed,",
                "whether any dialog is a consent dialog, or whether this activity",
                "falls within the scope of what the user is asked to consent to.",
                f"- Cookies on load: {pre_consent.total_cookies} ({pre_consent.tracking_cookies} matched tracking patterns)",
                f"- Scripts on load: {pre_consent.total_scripts} ({pre_consent.tracking_scripts} matched tracking patterns)",
                f"- Requests on load: {pre_consent.total_requests} ({pre_consent.tracker_requests} matched tracking patterns)",
            ]
        )
    return "\n".join(lines)
