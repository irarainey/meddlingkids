"""Tracking analysis agent for privacy risk assessment.

Generates a structured JSON privacy analysis by examining
cookies, scripts, network requests, and storage data.
Consistent with other agents' structured-output approach.
"""

from __future__ import annotations

from src.agents import base, config, context_builder
from src.agents.prompts import tracking_analysis
from src.analysis import domain_cache
from src.models import analysis, consent
from src.utils import json_parsing, logger

log = logger.create_logger("TrackingAnalysisAgent")


# ── Private response wrapper ───────────────────────────────────
# The LLM sees this schema via ``response_format``.  We map
# the parsed result to the public ``TrackingAnalysisResult``
# model in ``models.analysis`` before returning.

import pydantic  # noqa: E402 (grouped after local imports)  # noqa: important[wrong-import-order]


class _TrackingAnalysisResponse(pydantic.BaseModel):
    """Schema pushed to the LLM via ``response_format``."""

    risk_level: analysis.RiskLevel
    risk_summary: str
    sections: list[analysis.TrackingAnalysisSection]


# ── Agent class ─────────────────────────────────────────────────


class TrackingAnalysisAgent(base.BaseAgent):
    """Agent that generates structured privacy analysis reports.

    Uses ``response_format`` with a JSON schema to produce
    typed output, consistent with StructuredReportAgent and
    SummaryFindingsAgent.
    """

    agent_name = config.AGENT_TRACKING_ANALYSIS
    instructions = tracking_analysis.INSTRUCTIONS
    max_tokens = 2048
    max_retries = 5
    call_timeout = 90  # Large prompts (30K–50K chars) need more time
    response_model = _TrackingAnalysisResponse

    async def analyze(
        self,
        tracking_summary: analysis.TrackingSummary,
        consent_details: consent.ConsentDetails | None = None,
        pre_consent_stats: analysis.PreConsentStats | None = None,
        score_breakdown: analysis.ScoreBreakdown | None = None,
        domain_knowledge: domain_cache.DomainKnowledge | None = None,
        decoded_cookies: dict[str, object] | None = None,
    ) -> analysis.TrackingAnalysisResult:
        """Run the tracking analysis and return structured output.

        Args:
            tracking_summary: Collected tracking data summary.
            consent_details: Optional consent dialog info.
            pre_consent_stats: Optional pre-consent page-load stats.
            score_breakdown: Deterministic privacy score so the
                LLM can calibrate its risk assessment.
            domain_knowledge: Prior-run classifications for
                consistency anchoring.
            decoded_cookies: Decoded privacy cookie signals
                (USP, GPP, GA, Facebook, OneTrust, etc.).

        Returns:
            Structured ``TrackingAnalysisResult``.

        Raises:
            TimeoutError: If the LLM call exceeds
                ``call_timeout`` on every retry.
        """
        prompt = _build_user_prompt(
            tracking_summary,
            consent_details,
            pre_consent_stats,
            score_breakdown,
            domain_knowledge,
            decoded_cookies=decoded_cookies,
        )
        log.info(
            "Starting tracking analysis",
            {
                "promptChars": len(prompt),
                "hasConsent": consent_details is not None,
            },
        )

        response = await self._complete(prompt)

        parsed = self._parse_response(response, _TrackingAnalysisResponse)
        if parsed:
            result = analysis.TrackingAnalysisResult(
                risk_level=parsed.risk_level,
                risk_summary=parsed.risk_summary,
                sections=parsed.sections,
            )
            log.info(
                "Tracking analysis complete",
                {
                    "riskLevel": result.risk_level,
                    "sections": len(result.sections),
                },
            )
            return result

        # Fallback: try manual JSON parse from text
        log.warn("Structured parse failed — attempting text fallback")
        fallback = _parse_text_fallback(response.text)
        if fallback:
            log.info(
                "Text fallback succeeded",
                {
                    "riskLevel": fallback.risk_level,
                    "sections": len(fallback.sections),
                },
            )
            return fallback

        # Last resort: wrap the raw text as a single section
        log.warn("All parsing failed — wrapping raw text")
        return analysis.TrackingAnalysisResult(
            risk_level="medium",
            risk_summary="Unable to parse structured analysis.",
            sections=[
                analysis.TrackingAnalysisSection(
                    heading="Raw Analysis",
                    content=response.text or "",
                ),
            ],
        )


# ── Text fallback parser ────────────────────────────────────────


def _parse_text_fallback(
    text: str | None,
) -> analysis.TrackingAnalysisResult | None:
    """Try to parse a ``TrackingAnalysisResult`` from raw text.

    The LLM sometimes wraps JSON in code fences even when
    structured output is requested.  This falls back to
    ``json_parsing.load_json_from_text`` and then
    validates the result.

    Args:
        text: Raw response text.

    Returns:
        Parsed result or ``None`` on failure.
    """
    data = json_parsing.load_json_from_text(text)
    if data is None:
        return None
    try:
        return analysis.TrackingAnalysisResult.model_validate(data)
    except Exception:
        return None


# ── Prompt builders ─────────────────────────────────────────────


def _build_user_prompt(
    tracking_summary: analysis.TrackingSummary,
    consent_details: consent.ConsentDetails | None = None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
    score_breakdown: analysis.ScoreBreakdown | None = None,
    domain_knowledge: domain_cache.DomainKnowledge | None = None,
    *,
    decoded_cookies: dict[str, object] | None = None,
) -> str:
    """Build the user prompt from tracking data.

    Delegates the data-context assembly to the shared
    :mod:`context_builder` and wraps it with an instruction
    preamble and analysis request.

    Args:
        tracking_summary: Collected tracking data summary.
        consent_details: Optional consent dialog info.
        pre_consent_stats: Optional pre-consent page-load stats.
        score_breakdown: Deterministic privacy score.
        domain_knowledge: Prior-run domain classifications.

    Returns:
        Formatted user prompt string.
    """
    data_context = context_builder.build_analysis_context(
        tracking_summary,
        consent_details=consent_details,
        pre_consent_stats=pre_consent_stats,
        score_breakdown=score_breakdown,
        domain_knowledge=domain_knowledge,
        include_raw_consent_text=True,
        decoded_cookies=decoded_cookies,
    )
    return f"Analyze the following tracking data collected from: {tracking_summary.analyzed_url}\n\n{data_context}"
