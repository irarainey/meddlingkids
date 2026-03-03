"""Pydantic models for structured privacy analysis reports.

Defines the schema for each report section so the LLM
produces deterministic, structured output that the client
renders without free-form markdown parsing.
"""

from __future__ import annotations

from typing import Literal

import pydantic

from src.utils import serialization

# ── Shared entity with optional URL ─────────────────────────────


class NamedEntity(pydantic.BaseModel):
    """A company or service name with an optional URL.

    Used in shared_with lists and third-party service lists
    so the client can render names as clickable links.
    """

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel,
        populate_by_name=True,
    )

    name: str
    url: str = ""


def _coerce_named_entities(
    value: list[str | dict[str, str] | NamedEntity],
) -> list[NamedEntity]:
    """Accept plain strings or dicts and normalise to NamedEntity.

    The LLM returns plain strings; the enrichment step later
    populates URLs.  This validator lets both forms coexist.
    """
    result: list[NamedEntity] = []
    for item in value:
        if isinstance(item, NamedEntity):
            result.append(item)
        elif isinstance(item, dict):
            result.append(NamedEntity(**item))
        elif isinstance(item, str):
            result.append(NamedEntity(name=item))
        else:
            result.append(NamedEntity(name=str(item)))
    return result


# ── Section 1: Tracking Technologies ────────────────────────────


class TrackerEntry(pydantic.BaseModel):
    """A single identified tracking technology."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    name: str
    domains: list[str]
    cookies: list[str] = pydantic.Field(default_factory=list)
    storage_keys: list[str] = pydantic.Field(default_factory=list)
    purpose: str
    url: str = ""


class TrackingTechnologiesSection(pydantic.BaseModel):
    """Categorised tracking technologies found on the page."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    analytics: list[TrackerEntry] = pydantic.Field(default_factory=list)
    advertising: list[TrackerEntry] = pydantic.Field(default_factory=list)
    identity_resolution: list[TrackerEntry] = pydantic.Field(default_factory=list)
    social_media: list[TrackerEntry] = pydantic.Field(default_factory=list)
    other: list[TrackerEntry] = pydantic.Field(default_factory=list)


# ── Section 2: Data Collection ──────────────────────────────────


# Canonical risk / sensitive defaults for standard data-collection
# categories.  Enforced by a model validator on DataCollectionItem
# so that LLM drift cannot produce inconsistent results across runs.
_CANONICAL_CATEGORY_DEFAULTS: dict[str, tuple[Literal["low", "medium", "high", "critical"], bool]] = {
    "browsing behaviour": ("medium", False),
    "device information": ("medium", False),
    "location data": ("medium", False),
    "usage analytics": ("medium", False),
    "account & consent state": ("low", False),
    "experimentation & optimisation": ("low", False),
    "advertising & retargeting": ("high", False),
    "financial / payment": ("critical", True),
    "health & wellness": ("critical", True),
    "social media signals": ("medium", False),
}


class DataCollectionItem(pydantic.BaseModel):
    """A type of data being collected."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    category: str
    details: list[str]
    risk: Literal["low", "medium", "high", "critical"]
    sensitive: bool = False
    shared_with: list[NamedEntity] = pydantic.Field(default_factory=list)

    @pydantic.model_validator(mode="after")
    def _enforce_canonical_risk(self) -> DataCollectionItem:
        """Enforce consistent risk / sensitive for standard categories.

        For well-known categories the canonical values override
        whatever the LLM returned.  For any other category the
        general rule applies: 'critical' requires ``sensitive=True``.
        """
        defaults = _CANONICAL_CATEGORY_DEFAULTS.get(self.category.lower())
        if defaults is not None:
            self.risk, self.sensitive = defaults
        elif self.risk == "critical" and not self.sensitive:
            self.risk = "high"
        return self

    @pydantic.field_validator("shared_with", mode="before")
    @classmethod
    def _coerce_shared_with(
        cls,
        v: list[str | dict[str, str] | NamedEntity],
    ) -> list[NamedEntity]:
        return _coerce_named_entities(v)


class DataCollectionSection(pydantic.BaseModel):
    """What data the page collects from users."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    items: list[DataCollectionItem] = pydantic.Field(default_factory=list)


# ── Section 3: Third-Party Services ────────────────────────────


class ThirdPartyGroup(pydantic.BaseModel):
    """A categorised group of third-party services."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    category: str
    services: list[NamedEntity] = pydantic.Field(default_factory=list)
    privacy_impact: str

    @pydantic.field_validator("services", mode="before")
    @classmethod
    def _coerce_services(
        cls,
        v: list[str | dict[str, str] | NamedEntity],
    ) -> list[NamedEntity]:
        return _coerce_named_entities(v)


class ThirdPartySection(pydantic.BaseModel):
    """Third-party services contacted by the page."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    total_domains: int = 0
    groups: list[ThirdPartyGroup] = pydantic.Field(default_factory=list)
    summary: str = ""


# ── Section 4: Privacy Risk Assessment ─────────────────────────

RiskLevel = Literal["low", "medium", "high", "very-high"]


class RiskFactor(pydantic.BaseModel):
    """A specific factor contributing to risk level."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    description: str
    severity: Literal["low", "medium", "high", "critical"]


class PrivacyRiskSection(pydantic.BaseModel):
    """Overall privacy risk assessment."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    overall_risk: RiskLevel = "medium"
    factors: list[RiskFactor] = pydantic.Field(default_factory=list)
    summary: str = ""


# ── Section 5: Cookie Analysis ──────────────────────────────────


class CookieGroup(pydantic.BaseModel):
    """A group of cookies by purpose."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    category: str
    cookies: list[str]
    lifespan: str = ""
    concern_level: Literal["none", "low", "medium", "high"] = "none"


class CookieAnalysisSection(pydantic.BaseModel):
    """Analysis of cookies by purpose and risk."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    total: int = 0
    groups: list[CookieGroup] = pydantic.Field(default_factory=list)
    concerning_cookies: list[str] = pydantic.Field(default_factory=list)

    @pydantic.field_validator("groups", mode="after")
    @classmethod
    def _drop_empty_groups(cls, v: list[CookieGroup]) -> list[CookieGroup]:
        """Remove cookie groups with zero cookies."""
        return [g for g in v if g.cookies]


# ── Section 6: Storage Analysis ──────────────────────────────────


class StorageAnalysisSection(pydantic.BaseModel):
    """Analysis of localStorage and sessionStorage usage."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    local_storage_count: int = 0
    session_storage_count: int = 0
    local_storage_concerns: list[str] = pydantic.Field(default_factory=list)
    session_storage_concerns: list[str] = pydantic.Field(default_factory=list)
    summary: str = ""


# ── Section 7: Consent Analysis ─────────────────────────────────


class ConsentDiscrepancy(pydantic.BaseModel):
    """A discrepancy between consent claims and reality."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    claimed: str
    actual: str
    severity: Literal["low", "medium", "high", "critical"]


class ConsentAnalysisSection(pydantic.BaseModel):
    """Analysis of the consent dialog vs actual tracking."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    has_consent_dialog: bool = False
    categories_disclosed: int = 0
    partners_disclosed: int = 0
    discrepancies: list[ConsentDiscrepancy] = pydantic.Field(default_factory=list)
    summary: str = ""
    consent_platform: str | None = None
    consent_platform_url: str | None = None


# ── Section 8: Social Media Implications ────────────────────────


class SocialMediaRisk(pydantic.BaseModel):
    """A specific social media privacy risk."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel,
        populate_by_name=True,
    )

    platform: str
    risk: str
    severity: Literal["low", "medium", "high", "critical"]


class SocialMediaImplicationsSection(pydantic.BaseModel):
    """Analysis of social media tracking implications.

    Explains how detected social media integrations can
    link browsing activity to real identities when users
    are logged into those platforms.
    """

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel,
        populate_by_name=True,
    )

    platforms_detected: list[str] = pydantic.Field(
        default_factory=list,
    )
    identity_linking_risk: Literal["none", "low", "medium", "high"] = "none"
    risks: list[SocialMediaRisk] = pydantic.Field(
        default_factory=list,
    )
    summary: str = ""


# ── Section 9: Recommendations ──────────────────────────────────


class RecommendationGroup(pydantic.BaseModel):
    """A group of recommendations."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    category: str
    items: list[str]


class RecommendationsSection(pydantic.BaseModel):
    """Actionable recommendations for users."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    groups: list[RecommendationGroup] = pydantic.Field(default_factory=list)


# ── Complete Report ─────────────────────────────────────────────


class StructuredReport(pydantic.BaseModel):
    """Complete structured privacy analysis report.

    Each section is populated by a separate, focused LLM call
    so the output is deterministic and consistently formatted.
    """

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    tracking_technologies: TrackingTechnologiesSection = pydantic.Field(default_factory=TrackingTechnologiesSection)
    data_collection: DataCollectionSection = pydantic.Field(default_factory=DataCollectionSection)
    third_party_services: ThirdPartySection = pydantic.Field(default_factory=ThirdPartySection)
    privacy_risk: PrivacyRiskSection = pydantic.Field(default_factory=PrivacyRiskSection)
    cookie_analysis: CookieAnalysisSection = pydantic.Field(default_factory=CookieAnalysisSection)
    storage_analysis: StorageAnalysisSection = pydantic.Field(default_factory=StorageAnalysisSection)
    consent_analysis: ConsentAnalysisSection = pydantic.Field(default_factory=ConsentAnalysisSection)
    social_media_implications: SocialMediaImplicationsSection = pydantic.Field(
        default_factory=SocialMediaImplicationsSection,
    )
    recommendations: RecommendationsSection = pydantic.Field(default_factory=RecommendationsSection)
