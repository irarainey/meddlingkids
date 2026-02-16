"""Consent platform detection and CMP-specific strategy helpers.

Detects which Consent Management Platform (CMP) is active on a page
by checking DOM selectors, cookies, and JavaScript APIs.  When a CMP
is identified the module provides deterministic accept-button
selectors so the overlay pipeline can skip expensive LLM vision
calls for well-known platforms.

The platform profiles are loaded from ``data/consent/consent-platforms.json``.
"""

from __future__ import annotations

from typing import Any

from playwright import async_api

from src.data import loader
from src.utils import logger

log = logger.create_logger("ConsentPlatform")


# ────────────────────────────────────────────────────────────
# Types for consent platform data
# ────────────────────────────────────────────────────────────


class ConsentPlatformProfile:
    """In-memory representation of a CMP profile from the data file."""

    __slots__ = (
        "accept_button_patterns",
        "container_selectors",
        "cookie_indicators",
        "description",
        "iframe_patterns",
        "js_apis",
        "key",
        "manage_button_patterns",
        "name",
        "notes",
        "privacy_url",
        "reject_button_patterns",
        "tcf_registered",
        "vendor",
    )

    def __init__(self, key: str, data: dict[str, Any]) -> None:
        self.key = key
        self.name: str = data.get("name", key)
        self.vendor: str = data.get("vendor", "")
        self.privacy_url: str = data.get("privacy_url", "")
        self.tcf_registered: bool = data.get("tcf_registered", False)
        self.description: str = data.get("description", "")
        self.iframe_patterns: list[str] = data.get("iframe_patterns", [])
        self.container_selectors: list[str] = data.get("container_selectors", [])
        self.js_apis: list[str] = data.get("js_apis", [])
        self.cookie_indicators: list[str] = data.get("cookie_indicators", [])
        self.accept_button_patterns: list[str] = data.get("accept_button_patterns", [])
        self.reject_button_patterns: list[str] = data.get("reject_button_patterns", [])
        self.manage_button_patterns: list[str] = data.get("manage_button_patterns", [])
        self.notes: str = data.get("notes", "")


# ────────────────────────────────────────────────────────────
# Profile cache
# ────────────────────────────────────────────────────────────

_profiles_cache: dict[str, ConsentPlatformProfile] | None = None


def get_platform_profiles() -> dict[str, ConsentPlatformProfile]:
    """Load and cache all consent platform profiles."""
    global _profiles_cache
    if _profiles_cache is None:
        _profiles_cache = loader.load_consent_platforms()
    return _profiles_cache


def get_platform_profile(key: str) -> ConsentPlatformProfile | None:
    """Look up a single platform profile by key (case-insensitive)."""
    profiles = get_platform_profiles()
    return profiles.get(key.lower().replace(" ", "_"))


# ────────────────────────────────────────────────────────────
# Detection via page cookies
# ────────────────────────────────────────────────────────────


def detect_platform_from_cookies(
    cookies: list[dict[str, Any]],
) -> ConsentPlatformProfile | None:
    """Identify the active CMP from page cookies.

    Checks each platform's ``cookie_indicators`` against the
    cookie names present on the page.  Returns the first match
    with the most indicator hits.

    Args:
        cookies: List of cookie dicts (each must have a ``name`` key).

    Returns:
        The matched :class:`ConsentPlatformProfile`, or ``None``.
    """
    if not cookies:
        return None

    cookie_names = {c.get("name", "") for c in cookies}
    profiles = get_platform_profiles()

    best: ConsentPlatformProfile | None = None
    best_hits = 0

    for profile in profiles.values():
        hits = sum(1 for ind in profile.cookie_indicators if ind in cookie_names)
        if hits > best_hits:
            best_hits = hits
            best = profile

    if best and best_hits > 0:
        log.debug(
            "CMP detected from cookies",
            {"platform": best.name, "hits": best_hits},
        )
    return best if best_hits > 0 else None


# ────────────────────────────────────────────────────────────
# Detection via media group profile
# ────────────────────────────────────────────────────────────

# Map from media-groups.json consent_platform values to profile keys.
_MEDIA_GROUP_CMP_MAP: dict[str, str] = {
    "sourcepoint": "sourcepoint",
    "onetrust": "onetrust",
    "quantcast choice": "quantcast_choice",
    "quantcast": "quantcast_choice",
    "cookiebot": "cookiebot",
    "didomi": "didomi",
    "trustarc": "trustarc",
    "usercentrics": "usercentrics",
    "complianz": "complianz",
    "consentmanager": "consentmanager",
    "iubenda": "iubenda",
    "google funding choices": "funding_choices",
    "funding choices": "funding_choices",
    "osano": "osano",
    "termly": "termly",
    "cookie law info": "cookie_law_info",
    "cookieyes": "cookie_law_info",
    "sirdata": "sirdata",
    "sirdata cmp": "sirdata",
    "commander act": "commander_act",
    "commanders act": "commander_act",
    "crownpeak": "crownpeak",
    "admiral": "admiral",
    "axeptio": "axeptio",
}


def detect_platform_from_domain(domain: str) -> ConsentPlatformProfile | None:
    """Look up the CMP for a domain via the media group database.

    Uses :func:`~src.data.loader.find_media_group_by_domain` to
    check whether the domain belongs to a known media group and,
    if so, maps its ``consent_platform`` field to a profile.

    Args:
        domain: Base domain (e.g. ``"mirror.co.uk"``).

    Returns:
        The matched :class:`ConsentPlatformProfile`, or ``None``.
    """
    result = loader.find_media_group_by_domain(domain)
    if result is None:
        return None

    _, profile = result
    cmp_name = (profile.consent_platform or "").lower().strip()
    if not cmp_name:
        return None

    # Strip "custom" prefixes like "Custom BBC CMP" or
    # "Custom (account-based consent via ...)"
    if cmp_name.startswith("custom"):
        return None

    key = _MEDIA_GROUP_CMP_MAP.get(cmp_name)
    if key is None:
        # Try a fuzzy match against profile keys
        for map_key, profile_key in _MEDIA_GROUP_CMP_MAP.items():
            if map_key in cmp_name:
                key = profile_key
                break

    if key:
        matched = get_platform_profile(key)
        if matched:
            log.info(
                "CMP identified from media group profile",
                {"domain": domain, "platform": matched.name},
            )
            return matched

    return None


# ────────────────────────────────────────────────────────────
# Detection via page DOM (container selectors)
# ────────────────────────────────────────────────────────────


async def detect_platform_from_page(
    page: async_api.Page,
) -> ConsentPlatformProfile | None:
    """Detect which CMP is active by probing the page DOM.

    Tries each platform's ``container_selectors`` to see if
    any are present and visible in the page or inside matching
    consent iframes.  Returns the first match.

    This is fast (~50-100ms) compared to an LLM vision call
    (~3-5s) and can short-circuit the detection flow for
    well-known CMPs.

    Args:
        page: The Playwright page to inspect.

    Returns:
        The matched :class:`ConsentPlatformProfile`, or ``None``.
    """
    profiles = get_platform_profiles()

    # ── Check main frame first ──────────────────────────
    for profile in profiles.values():
        for selector in profile.container_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.is_visible(timeout=200):
                    log.info(
                        "CMP detected from DOM selector",
                        {
                            "platform": profile.name,
                            "selector": selector,
                        },
                    )
                    return profile
            except Exception:
                continue

    # ── Check consent iframes for CMP containers ────────
    # Some CMPs (e.g. consentmanager) render entirely inside
    # an iframe, so their container selectors won't appear in
    # the main frame.  Check iframes whose URL matches the
    # platform's iframe_patterns.
    for profile in profiles.values():
        if not profile.iframe_patterns:
            continue
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            frame_url = frame.url or ""
            if not any(pat in frame_url for pat in profile.iframe_patterns):
                continue
            # Found a matching consent iframe — check containers
            for selector in profile.container_selectors:
                try:
                    locator = frame.locator(selector).first
                    if await locator.is_visible(timeout=200):
                        log.info(
                            "CMP detected from iframe DOM selector",
                            {
                                "platform": profile.name,
                                "selector": selector,
                                "iframe": frame_url[:120],
                            },
                        )
                        return profile
                except Exception:
                    continue
            # Even if no container selector matched, the iframe
            # URL itself is strong evidence of the platform.
            log.info(
                "CMP detected from consent iframe URL",
                {
                    "platform": profile.name,
                    "iframe": frame_url[:120],
                },
            )
            return profile

    return None


# ────────────────────────────────────────────────────────────
# CMP-specific accept button helpers
# ────────────────────────────────────────────────────────────


async def find_accept_button(
    page: async_api.Page,
    profile: ConsentPlatformProfile,
) -> tuple[async_api.Locator, async_api.Frame, str] | None:
    """Try to find an accept button using CMP-specific selectors.

    Checks each selector from the profile's
    ``accept_button_patterns`` in the main frame and, if the
    CMP uses iframes, in all matching consent iframes.

    Args:
        page: The Playwright page to search.
        profile: The detected CMP profile.

    Returns:
        A tuple of ``(locator, frame, selector)`` if found,
        or ``None``.
    """
    # Try main frame first
    for selector in profile.accept_button_patterns:
        try:
            locator = page.locator(selector).first
            if await locator.is_visible(timeout=300):
                return locator, page.main_frame, selector
        except Exception:
            continue

    # Try consent iframes if the CMP uses them
    if profile.iframe_patterns:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            frame_url = frame.url or ""
            if not any(pat in frame_url for pat in profile.iframe_patterns):
                continue
            for selector in profile.accept_button_patterns:
                try:
                    locator = frame.locator(selector).first
                    if await locator.is_visible(timeout=300):
                        return locator, frame, selector
                except Exception:
                    continue

    return None


async def find_reject_button(
    page: async_api.Page,
    profile: ConsentPlatformProfile,
) -> tuple[async_api.Locator, async_api.Frame, str] | None:
    """Try to find a reject button using CMP-specific selectors.

    Same approach as :func:`find_accept_button` but using
    ``reject_button_patterns``.

    Args:
        page: The Playwright page to search.
        profile: The detected CMP profile.

    Returns:
        A tuple of ``(locator, frame, selector)`` if found,
        or ``None``.
    """
    for selector in profile.reject_button_patterns:
        try:
            locator = page.locator(selector).first
            if await locator.is_visible(timeout=300):
                return locator, page.main_frame, selector
        except Exception:
            continue

    if profile.iframe_patterns:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            frame_url = frame.url or ""
            if not any(pat in frame_url for pat in profile.iframe_patterns):
                continue
            for selector in profile.reject_button_patterns:
                try:
                    locator = frame.locator(selector).first
                    if await locator.is_visible(timeout=300):
                        return locator, frame, selector
                except Exception:
                    continue

    return None
