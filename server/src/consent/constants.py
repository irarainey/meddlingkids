"""Shared constants for consent-manager detection across the codebase."""

from __future__ import annotations

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
