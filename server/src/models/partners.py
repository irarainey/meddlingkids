"""Pydantic models for partner classification and risk assessment."""

from __future__ import annotations

import re
from typing import Literal

import pydantic

PartnerRiskLevel = Literal["critical", "high", "medium", "low", "unknown"]

PartnerCategoryType = Literal[
    "data-broker",
    "advertising",
    "cross-site-tracking",
    "identity-resolution",
    "analytics",
    "social-media",
    "content-delivery",
    "fraud-prevention",
    "personalization",
    "measurement",
    "unknown",
]


class PartnerEntry(pydantic.BaseModel):
    """Partner entry as stored in JSON."""

    concerns: list[str]
    aliases: list[str]


class ScriptPattern(pydantic.BaseModel):
    """Script pattern with pre-compiled regex for matching."""

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    pattern: str
    description: str
    compiled: re.Pattern[str] = pydantic.Field(exclude=True)


class PartnerCategoryConfig(pydantic.BaseModel):
    """Configuration for how a partner category should be classified."""

    file: str
    risk_level: PartnerRiskLevel
    category: PartnerCategoryType
    reason: str
    risk_score: int


class PartnerClassification(pydantic.BaseModel):
    """Classification result for a partner."""

    name: str
    risk_level: PartnerRiskLevel
    category: PartnerCategoryType
    reason: str
    concerns: list[str]
    risk_score: int


class PartnerRiskSummary(pydantic.BaseModel):
    """Quick risk summary for a set of consent partners."""

    critical_count: int
    high_count: int
    total_risk_score: int
    worst_partners: list[str]


class MediaGroupProfile(pydantic.BaseModel):
    """Profile of a media group or publisher conglomerate."""

    parent: str
    privacy_policy: str
    properties: list[str]
    domains: list[str]
    consent_platform: str
    key_vendors: list[str]
    privacy_characteristics: list[str]
