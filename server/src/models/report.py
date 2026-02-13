"""Pydantic models for structured privacy analysis reports.

Defines the schema for each report section so the LLM
produces deterministic, structured output that the client
renders without free-form markdown parsing.
"""

from __future__ import annotations

from typing import Literal

import pydantic
from src.utils import serialization


# ── Section 1: Tracking Technologies ────────────────────────────

class TrackerEntry(pydantic.BaseModel):
    """A single identified tracking technology."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    name: str
    domains: list[str]
    cookies: list[str] = pydantic.Field(default_factory=list)
    storage_keys: list[str] = pydantic.Field(default_factory=list)
    purpose: str


class TrackingTechnologiesSection(pydantic.BaseModel):
    """Categorised tracking technologies found on the page."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    analytics: list[TrackerEntry] = pydantic.Field(default_factory=list)
    advertising: list[TrackerEntry] = pydantic.Field(default_factory=list)
    identity_resolution: list[TrackerEntry] = pydantic.Field(default_factory=list)
    social_media: list[TrackerEntry] = pydantic.Field(default_factory=list)
    other: list[TrackerEntry] = pydantic.Field(default_factory=list)


# ── Section 2: Data Collection ──────────────────────────────────

class DataCollectionItem(pydantic.BaseModel):
    """A type of data being collected."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    category: str
    details: list[str]
    risk: Literal["low", "medium", "high", "critical"]
    sensitive: bool = False
    shared_with: list[str] = pydantic.Field(default_factory=list)


class DataCollectionSection(pydantic.BaseModel):
    """What data the page collects from users."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    items: list[DataCollectionItem] = pydantic.Field(default_factory=list)


# ── Section 3: Third-Party Services ────────────────────────────

class ThirdPartyGroup(pydantic.BaseModel):
    """A categorised group of third-party services."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    category: str
    services: list[str]
    privacy_impact: str


class ThirdPartySection(pydantic.BaseModel):
    """Third-party services contacted by the page."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    total_domains: int = 0
    groups: list[ThirdPartyGroup] = pydantic.Field(default_factory=list)
    summary: str = ""


# ── Section 4: Privacy Risk Assessment ─────────────────────────

RiskLevel = Literal["low", "medium", "high", "very-high"]


class RiskFactor(pydantic.BaseModel):
    """A specific factor contributing to risk level."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    description: str
    severity: Literal["low", "medium", "high", "critical"]


class PrivacyRiskSection(pydantic.BaseModel):
    """Overall privacy risk assessment."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    overall_risk: RiskLevel = "medium"
    factors: list[RiskFactor] = pydantic.Field(default_factory=list)
    summary: str = ""


# ── Section 5: Cookie Analysis ──────────────────────────────────

class CookieGroup(pydantic.BaseModel):
    """A group of cookies by purpose."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    category: str
    cookies: list[str]
    lifespan: str = ""
    concern_level: Literal["none", "low", "medium", "high"] = "none"


class CookieAnalysisSection(pydantic.BaseModel):
    """Analysis of cookies by purpose and risk."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    total: int = 0
    groups: list[CookieGroup] = pydantic.Field(default_factory=list)
    concerning_cookies: list[str] = pydantic.Field(default_factory=list)


# ── Section 6: Storage Analysis ──────────────────────────────────

class StorageAnalysisSection(pydantic.BaseModel):
    """Analysis of localStorage and sessionStorage usage."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    local_storage_count: int = 0
    session_storage_count: int = 0
    local_storage_concerns: list[str] = pydantic.Field(default_factory=list)
    session_storage_concerns: list[str] = pydantic.Field(default_factory=list)
    summary: str = ""


# ── Section 7: Consent Analysis ─────────────────────────────────

class ConsentDiscrepancy(pydantic.BaseModel):
    """A discrepancy between consent claims and reality."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    claimed: str
    actual: str
    severity: Literal["low", "medium", "high", "critical"]


class ConsentAnalysisSection(pydantic.BaseModel):
    """Analysis of the consent dialog vs actual tracking."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    has_consent_dialog: bool = False
    categories_disclosed: int = 0
    partners_disclosed: int = 0
    discrepancies: list[ConsentDiscrepancy] = pydantic.Field(default_factory=list)
    summary: str = ""


# ── Section 8: Key Vendors ──────────────────────────────────────

class VendorEntry(pydantic.BaseModel):
    """A key vendor/partner with privacy implications."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    name: str
    role: str
    privacy_impact: str


class VendorSection(pydantic.BaseModel):
    """Key vendors and their privacy implications."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    vendors: list[VendorEntry] = pydantic.Field(default_factory=list)


# ── Section 9: Recommendations ──────────────────────────────────

class RecommendationGroup(pydantic.BaseModel):
    """A group of recommendations."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    category: str
    items: list[str]


class RecommendationsSection(pydantic.BaseModel):
    """Actionable recommendations for users."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    groups: list[RecommendationGroup] = pydantic.Field(default_factory=list)


# ── Complete Report ─────────────────────────────────────────────

class StructuredReport(pydantic.BaseModel):
    """Complete structured privacy analysis report.

    Each section is populated by a separate, focused LLM call
    so the output is deterministic and consistently formatted.
    """

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel, populate_by_name=True
    )

    tracking_technologies: TrackingTechnologiesSection = pydantic.Field(
        default_factory=TrackingTechnologiesSection
    )
    data_collection: DataCollectionSection = pydantic.Field(
        default_factory=DataCollectionSection
    )
    third_party_services: ThirdPartySection = pydantic.Field(
        default_factory=ThirdPartySection
    )
    privacy_risk: PrivacyRiskSection = pydantic.Field(
        default_factory=PrivacyRiskSection
    )
    cookie_analysis: CookieAnalysisSection = pydantic.Field(
        default_factory=CookieAnalysisSection
    )
    storage_analysis: StorageAnalysisSection = pydantic.Field(
        default_factory=StorageAnalysisSection
    )
    consent_analysis: ConsentAnalysisSection = pydantic.Field(
        default_factory=ConsentAnalysisSection
    )
    key_vendors: VendorSection = pydantic.Field(
        default_factory=VendorSection
    )
    recommendations: RecommendationsSection = pydantic.Field(
        default_factory=RecommendationsSection
    )
