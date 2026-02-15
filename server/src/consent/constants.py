"""Shared constants for consent-manager detection across the codebase."""

from __future__ import annotations

import re
from urllib import parse

from playwright import async_api

# Consent-manager keywords matched against iframe **hostname** only.
# Matching the full URL would false-positive on ad-sync iframes that
# carry ``gdpr=1`` or ``gdpr_consent=…`` in their query strings.
CONSENT_HOST_KEYWORDS: tuple[str, ...] = (
    "consent",
    "onetrust",
    "cookiebot",
    "sourcepoint",
    "trustarc",
    "didomi",
    "quantcast",
    "gdpr",
    "privacy",
    "cmp",
    "cookie",
)

# Substrings in the hostname that indicate an ad-tech sync/pixel
# iframe rather than a real consent-manager frame.
CONSENT_HOST_EXCLUDE: tuple[str, ...] = (
    "cookie-sync",
    "pixel",
    "-sync.",
    "ad-sync",
    "user-sync",
    "match.",
    "prebid",
)

# Well-known container selectors for consent dialogs in the
# main frame (not inside iframes).
CONSENT_CONTAINER_SELECTORS: tuple[str, ...] = (
    "#qc-cmp2-ui",  # Quantcast
    "#onetrust-banner-sdk",  # OneTrust
    "#CybotCookiebotDialog",  # Cookiebot
    '[class*="consent"]',  # Generic
    '[id*="consent"]',  # Generic
    '[class*="cookie-banner"]',  # Generic
    '[id*="cookie-banner"]',  # Generic
)

# Reject-style button text patterns.  Used by the overlay
# pipeline and overlay cache to detect reject/decline buttons
# and prefer accept alternatives.
REJECT_BUTTON_RE: re.Pattern[str] = re.compile(
    r"reject|decline|deny|refuse|necessary only|essential only",
    re.IGNORECASE,
)


def is_consent_frame(
    frame: async_api.Frame,
    main_frame: async_api.Frame,
) -> bool:
    """Return ``True`` if *frame* looks like a consent-manager iframe.

    Checks the frame hostname against :data:`CONSENT_HOST_KEYWORDS`
    and :data:`CONSENT_HOST_EXCLUDE`.  Skips the main frame.
    """
    if frame == main_frame:
        return False
    try:
        hostname = parse.urlparse(frame.url).hostname or ""
    except Exception:
        return False
    hostname_lower = hostname.lower()
    if any(ex in hostname_lower for ex in CONSENT_HOST_EXCLUDE):
        return False
    return any(kw in hostname_lower for kw in CONSENT_HOST_KEYWORDS)
