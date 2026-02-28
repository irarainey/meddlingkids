"""Pydantic models for cookie consent detection and extraction."""

from __future__ import annotations

import re
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
    error: bool = False

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

    @classmethod
    def failed(cls, reason: str) -> CookieConsentDetection:
        """Return a detection result indicating an error.

        Unlike ``not_found``, this signals that detection
        could not be performed (e.g. timeout) rather than
        that no overlay was observed.
        """
        return cls(
            found=False,
            overlay_type=None,
            selector=None,
            button_text=None,
            confidence="low",
            reason=reason,
            error=True,
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
    privacy_url: str = ""

    @pydantic.field_validator("name", mode="after")
    @classmethod
    def _reject_non_partner_name(cls, v: str) -> str:
        """Reject values that look like article headlines, not company names."""
        if not is_plausible_partner_name(v):
            msg = f"Value rejected as partner name (looks like a headline): {v!r}"
            raise ValueError(msg)
        return v.strip()


class ConsentDetails(pydantic.BaseModel):
    """Detailed information extracted from a cookie consent dialog."""

    model_config = pydantic.ConfigDict(alias_generator=serialization.snake_to_camel, populate_by_name=True)

    has_manage_options: bool
    categories: list[ConsentCategory]
    partners: list[ConsentPartner]
    purposes: list[str]
    raw_text: str
    claimed_partner_count: int | None = None
    consent_platform: str | None = None

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


# ── Partner name plausibility check ─────────────────────────────

# Sentence-like patterns: verbs, articles, and punctuation that
# appear in headlines / prose but not in company names.
_HEADLINE_RE = re.compile(
    r"\b(?:evacuate|announce|report|warn|launch|reveal|confirm"
    r"|says?|said|told|claim|deny|vote|strike|attack|kill|arrest"
    r"|flee|condemn|urge|suspend|ban|approve|reject|sign"
    r"|explode|collapse|crash|burn|flood|earthquake|storm|die)"
    r"s?\b",
    re.IGNORECASE,
)

# Names that are clearly not data-processing partners — civic
# bodies, political entities, and generic topic labels that the
# LLM may extract from surrounding page content.
_NON_PARTNER_RE = re.compile(
    r"\b(?:council|government|parliament|ministry|department"
    r"|party|politics|election|borough|county|police"
    r"|commenting\s+content|read\s+more|subscribe)"
    r"\b",
    re.IGNORECASE,
)

# Maximum word count for a plausible company/vendor name.
# Real partners: "Google", "The Trade Desk", "Integral Ad Science".
_MAX_PARTNER_WORDS = 8

# Minimum length for a partner name.
_MIN_PARTNER_LENGTH = 2


def is_plausible_partner_name(name: str) -> bool:
    """Return ``True`` when *name* looks like a company name.

    Rejects values that resemble article headlines or prose
    sentences, which the LLM may extract from surrounding
    page content.

    Heuristics:

    * **Too long:** More than ``_MAX_PARTNER_WORDS`` words.
      Real vendor names rarely exceed 5-6 words.
    * **Too short:** Fewer than ``_MIN_PARTNER_LENGTH`` chars.
    * **Headline verbs:** Contains common news-headline verbs
      ("evacuates", "announces", "reports", etc.).
    * **Trailing ellipsis/punctuation:** Ends with ``...`` or
      ``!`` — typical of truncated headlines, not company
      names.
    """
    stripped = name.strip()
    if len(stripped) < _MIN_PARTNER_LENGTH:
        return False
    words = stripped.split()
    if len(words) > _MAX_PARTNER_WORDS:
        return False
    if stripped.endswith("...") or stripped.endswith("!"):
        return False
    if _NON_PARTNER_RE.search(stripped):
        return False
    return not _HEADLINE_RE.search(stripped)
