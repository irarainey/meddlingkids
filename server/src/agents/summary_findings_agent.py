"""Summary findings agent for structured privacy findings.

Generates a prioritised list of key privacy findings from
a full tracking analysis using structured JSON output.
"""

from __future__ import annotations

from typing import Literal

import pydantic
from src.agents import base, config
from src.models import analysis
from src.utils import json_parsing, logger, risk

log = logger.create_logger("SummaryFindingsAgent")


# ── Structured output models ───────────────────────────────────

class _SummaryFinding(pydantic.BaseModel):
    """A single finding returned by the LLM."""

    type: Literal[
        "critical", "high", "moderate", "info", "positive"
    ]
    text: str


class _SummaryFindingsResponse(pydantic.BaseModel):
    """Schema pushed to the LLM via ``response_format``."""

    findings: list[_SummaryFinding] = pydantic.Field(
        default_factory=list
    )


# ── System prompt ───────────────────────────────────────────────

_INSTRUCTIONS = """\
You are a privacy expert. Analyse the tracking data and \
create a structured summary of the key findings.

Each finding should have:
- "type": One of "critical", "high", "moderate", "info", \
"positive"
- "text": A single sentence describing the finding. Be \
specific about company names.

Severity decision criteria (apply strictly):
- "critical": Deceptive practices, data broker involvement, \
fingerprinting for cross-site identity, selling personal data, \
or consent dialog actively hiding significant tracking.
- "high": Persistent cross-session tracking via third-party \
identifiers, undisclosed advertising networks, pre-consent \
tracking scripts that bypass user choice.
- "moderate": Standard analytics with pseudonymous IDs, \
automated audience measurement, typical third-party media \
analytics.
- "info": Neutral observations about cookies, storage, or \
consent mechanisms without clear privacy harm.
- "positive": Privacy-respecting practices such as no \
advertising, minimal tracking, or strong consent controls.

You will also be given the site's deterministic privacy score \
(0-100) and its risk classification. Calibrate your severity \
labels to be consistent with this score. Do NOT use "critical" \
or "high" severity for a site scored as Low or Very Low Risk \
unless a specific practice genuinely warrants it — for example, \
data broker involvement or deceptive dark patterns. Conversely, \
do not understate findings for a high-scoring site.

Return exactly 6 findings, ordered by severity \
(most severe first, positive last).

Example output for a site scoring 35/100 (Low Risk) with \
analytics tracking and no advertising:
{"findings": [
  {"type": "high", "text": "Site loads Comscore and Chartbeat \
analytics scripts before user consent, bypassing the consent \
dialog."},
  {"type": "moderate", "text": "DotMetrics sets persistent \
cookies that enable cross-session audience measurement."},
  {"type": "moderate", "text": "Audience data is shared with \
three third-party analytics providers for media measurement."},
  {"type": "moderate", "text": "Scroll depth and time-on-page \
metrics are collected for behavioural engagement analytics."},
  {"type": "info", "text": "Consent dialog groups all optional \
tracking under a single vague category without listing \
partners."},
  {"type": "positive", "text": "No advertising networks, \
retargeting, or data broker integrations are present."}
]}

Return ONLY a JSON object matching the required schema."""


# ── Agent class ─────────────────────────────────────────────────

class SummaryFindingsAgent(base.BaseAgent):
    """Text agent that produces structured summary findings.

    Takes a full privacy analysis and distils it into a
    prioritised list of typed findings.
    """

    agent_name = config.AGENT_SUMMARY_FINDINGS
    instructions = _INSTRUCTIONS
    max_tokens = 500
    max_retries = 5
    response_model = _SummaryFindingsResponse

    async def summarise(
        self,
        analysis_text: str,
        score_breakdown: analysis.ScoreBreakdown | None = None,
    ) -> list[analysis.SummaryFinding]:
        """Generate summary findings from analysis text.

        Args:
            analysis_text: Full markdown privacy analysis.
            score_breakdown: Deterministic privacy score, if
                available, so the LLM can calibrate severity.

        Returns:
            List of typed ``SummaryFinding`` objects.
        """
        log.start_timer("summary-generation")
        log.info("Generating summary findings...")

        score_ctx = ""
        if score_breakdown:
            label = risk.risk_label(score_breakdown.total_score)
            top = ", ".join(
                score_breakdown.factors[:5]
            ) or "none"
            score_ctx = (
                f"\n\nDeterministic privacy score: "
                f"{score_breakdown.total_score}/100 "
                f"({label}). Top scoring factors: {top}.\n"
                f"Calibrate your severity labels to be "
                f"consistent with this score."
            )

        try:
            response = await self._complete(
                f"Based on this full analysis, create a"
                f" structured JSON object with key"
                f" findings:\n\n{analysis_text}"
                f"{score_ctx}"
            )
            log.end_timer(
                "summary-generation", "Summary generated"
            )

            parsed = self._parse_response(
                response, _SummaryFindingsResponse
            )
            if parsed:
                findings = [
                    analysis.SummaryFinding(
                        type=f.type, text=f.text
                    )
                    for f in parsed.findings
                ]
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
        items = (
            raw.get("findings", raw)
            if isinstance(raw, dict)
            else raw
        )
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
