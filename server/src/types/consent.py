"""Pydantic models for cookie consent detection and extraction."""

from __future__ import annotations

from typing import Literal

import pydantic

OverlayType = Literal[
    "cookie-consent",
    "sign-in",
    "newsletter",
    "paywall",
    "age-verification",
    "other",
]

ConfidenceLevel = Literal["high", "medium", "low"]


class CookieConsentDetection(pydantic.BaseModel):
    """Result of LLM vision analysis for detecting consent banners."""

    found: bool
    overlay_type: OverlayType | None
    selector: str | None
    button_text: str | None
    confidence: ConfidenceLevel
    reason: str


class ConsentCategory(pydantic.BaseModel):
    """A cookie category disclosed in a consent dialog."""

    name: str
    description: str
    required: bool


class ConsentPartner(pydantic.BaseModel):
    """A third-party partner/vendor listed in a consent dialog."""

    name: str
    purpose: str
    data_collected: list[str]
    risk_level: str | None = None
    risk_category: str | None = None
    risk_score: int | None = None
    concerns: list[str] | None = None


class ConsentDetails(pydantic.BaseModel):
    """Detailed information extracted from a cookie consent dialog."""

    has_manage_options: bool
    manage_options_selector: str | None
    categories: list[ConsentCategory]
    partners: list[ConsentPartner]
    purposes: list[str]
    raw_text: str
    expanded: bool | None = None
