"""Pydantic models for partner classification and risk assessment."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

PartnerRiskLevel = Literal[
    "critical", "high", "medium", "low", "unknown"
]

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


class PartnerEntry(BaseModel):
    """Partner entry as stored in JSON."""

    concerns: list[str]
    aliases: list[str]


class ScriptPattern(BaseModel):
    """Compiled script pattern with regex ready for matching."""

    pattern: str
    description: str


class PartnerCategoryConfig(BaseModel):
    """Configuration for how a partner category should be classified."""

    file: str
    risk_level: PartnerRiskLevel
    category: PartnerCategoryType
    reason: str
    risk_score: int


class PartnerClassification(BaseModel):
    """Classification result for a partner."""

    name: str
    risk_level: PartnerRiskLevel
    category: PartnerCategoryType
    reason: str
    concerns: list[str]
    risk_score: int


class PartnerRiskSummary(BaseModel):
    """Quick risk summary for a set of consent partners."""

    critical_count: int
    high_count: int
    total_risk_score: int
    worst_partners: list[str]
