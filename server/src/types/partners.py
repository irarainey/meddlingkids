"""Pydantic models for partner classification and risk assessment."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    """Script pattern with pre-compiled regex for matching."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    pattern: str
    description: str
    compiled: re.Pattern[str] = Field(exclude=True)


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
