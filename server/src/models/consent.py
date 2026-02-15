"""Pydantic models for cookie consent detection and extraction."""

from __future__ import annotations

from typing import Literal

import pydantic

from src.utils import serialization

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

    @classmethod
    def not_found(cls, reason: str = "") -> CookieConsentDetection:
        """Return a default *not-found* detection result."""
        return cls(
            found=False,
            overlay_type=None,
            selector=None,
            button_text=None,
            confidence="low",
            reason=reason,
        )


class ConsentCategory(pydantic.BaseModel):
    """A cookie category disclosed in a consent dialog."""

    name: str
    description: str
    required: bool


class ConsentPartner(pydantic.BaseModel):
    """A third-party partner/vendor listed in a consent dialog."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    name: str
    purpose: str
    data_collected: list[str]
    risk_level: str | None = None
    risk_category: str | None = None
    risk_score: int | None = None
    concerns: list[str] | None = None
    url: str = ""


class ConsentDetails(pydantic.BaseModel):
    """Detailed information extracted from a cookie consent dialog."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    has_manage_options: bool
    categories: list[ConsentCategory]
    partners: list[ConsentPartner]
    purposes: list[str]
    raw_text: str
    claimed_partner_count: int | None = None

    @classmethod
    def empty(
        cls,
        raw_text: str = "",
        claimed_partner_count: int | None = None,
    ) -> ConsentDetails:
        """Return a default empty consent-details result."""
        return cls(
            has_manage_options=False,
            categories=[],
            partners=[],
            purposes=[],
            raw_text=raw_text,
            claimed_partner_count=claimed_partner_count,
        )
