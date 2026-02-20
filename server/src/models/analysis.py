"""Pydantic models for analysis results, scoring, and domain breakdowns."""

from __future__ import annotations

from typing import Literal

import pydantic

from src.models import tracking_data
from src.utils import serialization


class DomainData(pydantic.BaseModel):
    """Tracking data grouped by domain."""

    cookies: list[tracking_data.TrackedCookie] = pydantic.Field(default_factory=list)
    scripts: list[tracking_data.TrackedScript] = pydantic.Field(default_factory=list)
    network_requests: list[tracking_data.NetworkRequest] = pydantic.Field(default_factory=list)


class DomainBreakdown(pydantic.BaseModel):
    """Summary statistics for a single domain's tracking activity."""

    domain: str
    cookie_count: int
    cookie_names: list[str]
    script_count: int
    request_count: int
    request_types: list[str]


class TrackingSummary(pydantic.BaseModel):
    """Complete summary of tracking data collected from a page."""

    analyzed_url: str
    total_cookies: int
    total_scripts: int
    total_network_requests: int
    local_storage_items: int
    session_storage_items: int
    third_party_domains: list[str]
    domain_breakdown: list[DomainBreakdown]
    local_storage: list[dict[str, str]]
    session_storage: list[dict[str, str]]


SummaryFindingType = Literal["critical", "high", "moderate", "info", "positive"]


class SummaryFinding(pydantic.BaseModel):
    """A single finding in the summary."""

    type: SummaryFindingType
    text: str


class CategoryScore(pydantic.BaseModel):
    """Score for an individual category."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    points: int = 0
    max_points: int = 0
    issues: list[str] = pydantic.Field(default_factory=list)


class PreConsentStats(pydantic.BaseModel):
    """Categorised page-load data snapshot.

    Captures both raw totals and *classified* counts so the
    consent scorer can assess actual tracking activity
    rather than raw infrastructure volume.  Modern sites
    legitimately load dozens of scripts and make hundreds of
    requests just to render — only items that match known
    tracker patterns are flagged as tracking activity.

    This snapshot is taken before any overlay or dialog is
    dismissed.  We cannot determine from this data whether
    observed scripts actually use the cookies present,
    whether a dialog is a consent dialog, or whether the
    tracked activity falls within the scope of what the
    user is asked to consent to.
    """

    # Raw totals (for logging / context only)
    total_cookies: int = 0
    total_scripts: int = 0
    total_requests: int = 0
    total_local_storage: int = 0
    total_session_storage: int = 0

    # Classified counts (used for scoring)
    tracking_cookies: int = 0
    tracking_scripts: int = 0
    tracker_requests: int = 0


class ScoreBreakdown(pydantic.BaseModel):
    """Detailed breakdown of how the score was calculated."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    total_score: int = 0
    categories: dict[str, CategoryScore] = pydantic.Field(default_factory=dict)
    factors: list[str] = pydantic.Field(default_factory=list)
    summary: str = ""


# ── Tracking analysis output ───────────────────────────────────

RiskLevel = Literal["low", "medium", "high", "very_high"]


class TrackingAnalysisSection(pydantic.BaseModel):
    """A single section of the tracking analysis."""

    heading: str = pydantic.Field(
        description="Section heading matching one of the required analysis areas",
    )
    content: str = pydantic.Field(
        description="Detailed analysis text for this section",
    )


class TrackingAnalysisResult(pydantic.BaseModel):
    """Structured output from TrackingAnalysisAgent.

    Captures the same analytical content previously returned
    as free-form Markdown, now in a typed JSON envelope that
    is consistent with other agents.
    """

    risk_level: RiskLevel = pydantic.Field(
        description="Overall privacy risk level",
    )
    risk_summary: str = pydantic.Field(
        description="One-paragraph summary of the overall privacy risk",
    )
    sections: list[TrackingAnalysisSection] = pydantic.Field(
        default_factory=list,
        description=(
            "Ordered analysis sections covering tracking technologies, "
            "data collection, third-party services, cookies, storage, "
            "consent analysis, partner/vendor analysis, and recommendations"
        ),
    )

    def to_text(self) -> str:
        """Serialise the analysis to plain text.

        Used when feeding the result to downstream agents
        (e.g. SummaryFindingsAgent) that expect a text
        representation.

        Returns:
            Human-readable text rendering of the analysis.
        """
        lines = [
            f"Risk Level: {self.risk_level}",
            f"Risk Summary: {self.risk_summary}",
            "",
        ]
        for section in self.sections:
            lines.append(f"## {section.heading}")
            lines.append(section.content)
            lines.append("")
        return "\n".join(lines)
