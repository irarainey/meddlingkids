"""Summary findings agent for structured privacy findings.

Generates a prioritised list of key privacy findings from
a full tracking analysis using structured JSON output.
"""

from __future__ import annotations

from typing import Literal

import pydantic

from src.agents import base, config
from src.models import analysis
from src.utils import logger
from src.utils.json_parsing import load_json_from_text

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

Types explained:
- "critical": Cross-site tracking, fingerprinting, data \
selling, deceptive practices
- "high": Persistent tracking, third-party data sharing, \
advertising networks
- "moderate": Standard analytics, typical ad tracking
- "info": General information about cookies or consent
- "positive": Privacy-respecting practices, minimal \
tracking, good practices

Return 5-7 findings maximum, ordered by severity \
(critical first, positive last).

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
    ) -> list[analysis.SummaryFinding]:
        """Generate summary findings from analysis text.

        Args:
            analysis_text: Full markdown privacy analysis.

        Returns:
            List of typed ``SummaryFinding`` objects.
        """
        log.start_timer("summary-generation")
        log.info("Generating summary findings...")

        try:
            response = await self._complete(
                f"Based on this full analysis, create a"
                f" structured JSON object with key"
                f" findings:\n\n{analysis_text}"
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
    raw = load_json_from_text(text)
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
