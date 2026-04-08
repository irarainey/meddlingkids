"""Consent platform detection and CMP-specific strategy helpers.

Detects which Consent Management Platform (CMP) is active on a page
by checking DOM selectors, cookies, and JavaScript APIs.  When a CMP
is identified the module provides deterministic accept-button
selectors so the overlay pipeline can skip expensive LLM vision
calls for well-known platforms.

The platform profiles are loaded from ``data/consent/consent-platforms.json``.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping, Sequence
from typing import Any

from playwright import async_api

from src.data import loader
from src.models import consent
from src.utils import logger

log = logger.create_logger("ConsentPlatform")

# Re-export so existing ``platform_detection.ConsentPlatformProfile``
# references continue to work.
ConsentPlatformProfile = consent.ConsentPlatformProfile
__all__ = ["ConsentPlatformProfile"]


# ────────────────────────────────────────────────────────────
# Profile cache
# ────────────────────────────────────────────────────────────


@functools.cache
def get_platform_profiles() -> dict[str, consent.ConsentPlatformProfile]:
    """Load and cache all consent platform profiles."""
    return loader.load_consent_platforms()


def get_platform_profile(key: str) -> consent.ConsentPlatformProfile | None:
    """Look up a single platform profile by key (case-insensitive)."""
    profiles = get_platform_profiles()
    return profiles.get(key.lower().replace(" ", "_"))


# ────────────────────────────────────────────────────────────
# Detection via page cookies
# ────────────────────────────────────────────────────────────


def detect_platform_from_cookies(
    cookies: Sequence[Mapping[str, Any]],
) -> consent.ConsentPlatformProfile | None:
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

    best: consent.ConsentPlatformProfile | None = None
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
    "inmobi choice": "inmobi_choice",
    "inmobi": "inmobi_choice",
    "quantcast choice": "inmobi_choice",
    "quantcast": "inmobi_choice",
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


def detect_platform_from_domain(domain: str) -> consent.ConsentPlatformProfile | None:
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
) -> consent.ConsentPlatformProfile | None:
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
                log.debug(
                    "DOM selector probe failed",
                    {"platform": profile.name, "selector": selector},
                )
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
                    log.debug(
                        "Iframe selector probe failed",
                        {"platform": profile.name, "selector": selector},
                    )
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
# CMP-specific button helpers
# ────────────────────────────────────────────────────────────


async def _find_button_by_patterns(
    page: async_api.Page,
    profile: consent.ConsentPlatformProfile,
    patterns: list[str],
    label: str,
) -> tuple[async_api.Locator, async_api.Frame, str] | None:
    """Search for a visible button matching *patterns*.

    Checks each CSS selector in the main frame first, then
    in consent iframes when the CMP profile declares
    ``iframe_patterns``.

    Args:
        page: The Playwright page to search.
        profile: The detected CMP profile.
        patterns: CSS selectors to probe (e.g.
            ``profile.accept_button_patterns``).
        label: Human-readable button kind for log messages
            (e.g. ``"Accept"`` or ``"Reject"``).

    Returns:
        A tuple of ``(locator, frame, selector)`` if found,
        or ``None``.
    """
    # Try main frame first
    for selector in patterns:
        try:
            locator = page.locator(selector).first
            if await locator.is_visible(timeout=300):
                return locator, page.main_frame, selector
        except Exception:
            log.debug(
                f"{label} button selector probe failed",
                {"platform": profile.name, "selector": selector},
            )
            continue

    # Try consent iframes if the CMP uses them
    if profile.iframe_patterns:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            frame_url = frame.url or ""
            if not any(pat in frame_url for pat in profile.iframe_patterns):
                continue
            for selector in patterns:
                try:
                    locator = frame.locator(selector).first
                    if await locator.is_visible(timeout=300):
                        return locator, frame, selector
                except Exception:
                    log.debug(
                        f"{label} button iframe selector probe failed",
                        {"platform": profile.name, "selector": selector},
                    )
                    continue

    return None


async def find_accept_button(
    page: async_api.Page,
    profile: consent.ConsentPlatformProfile,
) -> tuple[async_api.Locator, async_api.Frame, str] | None:
    """Try to find an accept button using CMP-specific selectors.

    Args:
        page: The Playwright page to search.
        profile: The detected CMP profile.

    Returns:
        A tuple of ``(locator, frame, selector)`` if found,
        or ``None``.
    """
    return await _find_button_by_patterns(
        page,
        profile,
        profile.accept_button_patterns,
        "Accept",
    )
