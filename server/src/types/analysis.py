"""Pydantic models for analysis results, scoring, and domain breakdowns."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.types.tracking_data import NetworkRequest, TrackedCookie, TrackedScript


class DomainData(BaseModel):
    """Tracking data grouped by domain."""

    cookies: list[TrackedCookie] = Field(default_factory=list)
    scripts: list[TrackedScript] = Field(default_factory=list)
    network_requests: list[NetworkRequest] = Field(
        default_factory=list
    )


class DomainBreakdown(BaseModel):
    """Summary statistics for a single domain's tracking activity."""

    domain: str
    cookie_count: int
    cookie_names: list[str]
    script_count: int
    request_count: int
    request_types: list[str]


class TrackingSummary(BaseModel):
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


SummaryFindingType = Literal[
    "critical", "high", "moderate", "info", "positive"
]


class SummaryFinding(BaseModel):
    """A single finding in the summary."""

    type: SummaryFindingType
    text: str


class CategoryScore(BaseModel):
    """Score for an individual category."""

    points: int = 0
    max_points: int = 0
    issues: list[str] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    """Detailed breakdown of how the score was calculated."""

    total_score: int = 0
    categories: dict[str, CategoryScore] = Field(
        default_factory=dict
    )
    factors: list[str] = Field(default_factory=list)
    summary: str = ""


class AnalysisResult(BaseModel):
    """Result of the AI-powered tracking analysis."""

    success: bool
    analysis: str | None = None
    summary_findings: list[SummaryFinding] | None = None
    privacy_score: int | None = None
    privacy_summary: str | None = None
    score_breakdown: ScoreBreakdown | None = None
    summary: TrackingSummary | None = None
    error: str | None = None
