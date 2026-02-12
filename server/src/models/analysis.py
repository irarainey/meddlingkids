"""Pydantic models for analysis results, scoring, and domain breakdowns."""

from __future__ import annotations

from typing import Literal

import pydantic

from src.models import tracking_data
from src.utils.serialization import snake_to_camel


class DomainData(pydantic.BaseModel):
    """Tracking data grouped by domain."""

    cookies: list[tracking_data.TrackedCookie] = pydantic.Field(default_factory=list)
    scripts: list[tracking_data.TrackedScript] = pydantic.Field(default_factory=list)
    network_requests: list[tracking_data.NetworkRequest] = pydantic.Field(
        default_factory=list
    )


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


SummaryFindingType = Literal[
    "critical", "high", "moderate", "info", "positive"
]


class SummaryFinding(pydantic.BaseModel):
    """A single finding in the summary."""

    type: SummaryFindingType
    text: str


class CategoryScore(pydantic.BaseModel):
    """Score for an individual category."""

    model_config = pydantic.ConfigDict(
        alias_generator=snake_to_camel, populate_by_name=True
    )

    points: int = 0
    max_points: int = 0
    issues: list[str] = pydantic.Field(default_factory=list)


class ScoreBreakdown(pydantic.BaseModel):
    """Detailed breakdown of how the score was calculated."""

    model_config = pydantic.ConfigDict(
        alias_generator=snake_to_camel, populate_by_name=True
    )

    total_score: int = 0
    categories: dict[str, CategoryScore] = pydantic.Field(
        default_factory=dict
    )
    factors: list[str] = pydantic.Field(default_factory=list)
    summary: str = ""
