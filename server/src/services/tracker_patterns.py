"""
Known tracker classification patterns for privacy scoring.

Compiled regex patterns used to identify and categorise tracking technologies
by type: high-risk (fingerprinting, session replay, data brokers),
advertising networks, social media trackers, analytics platforms,
tracking cookies, and storage patterns.
"""

from __future__ import annotations

import re

# ============================================================================
# Script / URL Tracker Patterns
# ============================================================================

HIGH_RISK_TRACKERS: list[re.Pattern[str]] = [
    re.compile(r"fingerprint|fpjs|fingerprintjs", re.I),
    re.compile(r"clarity\.ms"),
    re.compile(r"fullstory", re.I),
    re.compile(r"hotjar", re.I),
    re.compile(r"logrocket", re.I),
    re.compile(r"session.?replay", re.I),
    re.compile(r"mouseflow", re.I),
    re.compile(r"smartlook", re.I),
    re.compile(r"luckyorange", re.I),
    re.compile(r"inspectlet", re.I),
    re.compile(r"bluekai", re.I),
    re.compile(r"oracle.*cloud", re.I),
    re.compile(r"liveramp", re.I),
    re.compile(r"acxiom", re.I),
    re.compile(r"experian", re.I),
    re.compile(r"lotame", re.I),
    re.compile(r"neustar", re.I),
    re.compile(r"tapad", re.I),
    re.compile(r"drawbridge", re.I),
    re.compile(r"crossdevice", re.I),
    re.compile(r"id5", re.I),
    re.compile(r"unified.?id", re.I),
    re.compile(r"thetradedesk", re.I),
    re.compile(r"adsrvr\.org"),
]

ADVERTISING_TRACKERS: list[re.Pattern[str]] = [
    re.compile(r"doubleclick", re.I),
    re.compile(r"googlesyndication", re.I),
    re.compile(r"googleadservices", re.I),
    re.compile(r"google.*(ads|adwords)", re.I),
    re.compile(r"facebook.*pixel|fbevents|connect\.facebook", re.I),
    re.compile(r"amazon-adsystem", re.I),
    re.compile(r"criteo", re.I),
    re.compile(r"adnxs|appnexus", re.I),
    re.compile(r"rubiconproject|magnite", re.I),
    re.compile(r"pubmatic", re.I),
    re.compile(r"openx", re.I),
    re.compile(r"outbrain", re.I),
    re.compile(r"taboola", re.I),
    re.compile(r"bidswitch", re.I),
    re.compile(r"casalemedia|indexexchange", re.I),
    re.compile(r"adroll", re.I),
    re.compile(r"bing.*ads|bat\.bing", re.I),
    re.compile(r"tiktok.*pixel|analytics\.tiktok", re.I),
    re.compile(r"snapchat.*pixel|sc-static", re.I),
    re.compile(r"pinterest.*tag|pinimg.*tag", re.I),
    re.compile(r"linkedin.*insight|snap\.licdn", re.I),
    re.compile(r"twitter.*pixel|ads-twitter", re.I),
    re.compile(r"media\.net", re.I),
    re.compile(r"33across", re.I),
    re.compile(r"sharethrough", re.I),
]

SOCIAL_MEDIA_TRACKERS: list[re.Pattern[str]] = [
    re.compile(r"facebook\.net|facebook\.com.*sdk|fbcdn", re.I),
    re.compile(r"twitter\.com.*widgets|platform\.twitter", re.I),
    re.compile(r"linkedin\.com.*insight|platform\.linkedin", re.I),
    re.compile(r"pinterest\.com.*pinit", re.I),
    re.compile(r"tiktok\.com", re.I),
    re.compile(r"instagram\.com", re.I),
    re.compile(r"snapchat\.com", re.I),
    re.compile(r"reddit\.com.*pixel", re.I),
    re.compile(r"addthis", re.I),
    re.compile(r"sharethis", re.I),
    re.compile(r"addtoany", re.I),
]

ANALYTICS_TRACKERS: list[re.Pattern[str]] = [
    re.compile(r"google-analytics|googletagmanager.*gtag", re.I),
    re.compile(r"analytics\.google", re.I),
    re.compile(r"segment\.com|segment\.io", re.I),
    re.compile(r"amplitude", re.I),
    re.compile(r"mixpanel", re.I),
    re.compile(r"heap\.io|heapanalytics", re.I),
    re.compile(r"matomo|piwik", re.I),
    re.compile(r"chartbeat", re.I),
    re.compile(r"parsely", re.I),
    re.compile(r"newrelic", re.I),
    re.compile(r"datadog", re.I),
    re.compile(r"sentry\.io", re.I),
]

# ============================================================================
# Cookie Patterns
# ============================================================================

TRACKING_COOKIE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^_ga|^_gid|^_gat", re.I),
    re.compile(r"^_fbp|^_fbc", re.I),
    re.compile(r"^_gcl", re.I),
    re.compile(r"^_uet", re.I),
    re.compile(r"^__utm", re.I),
    re.compile(r"^_hjid|^_hjSession", re.I),
    re.compile(r"^_clck|^_clsk", re.I),
    re.compile(r"^IDE|^DSID|^FLC", re.I),
    re.compile(r"^NID|^SID|^HSID|^SSID|^APISID|^SAPISID", re.I),
    re.compile(r"^fr$", re.I),
    re.compile(r"^personalization_id|^guest_id", re.I),
    re.compile(r"^lidc|^bcookie|^bscookie", re.I),
    re.compile(r"criteo", re.I),
    re.compile(r"adroll", re.I),
    re.compile(r"taboola", re.I),
    re.compile(r"outbrain", re.I),
]

FINGERPRINT_COOKIE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"fingerprint", re.I),
    re.compile(r"fpjs", re.I),
    re.compile(r"device.?id", re.I),
    re.compile(r"browser.?id", re.I),
    re.compile(r"visitor.?id", re.I),
    re.compile(r"unique.?id", re.I),
    re.compile(r"client.?id", re.I),
]

# ============================================================================
# Storage Patterns
# ============================================================================

TRACKING_STORAGE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"amplitude", re.I),
    re.compile(r"segment", re.I),
    re.compile(r"mixpanel", re.I),
    re.compile(r"analytics", re.I),
    re.compile(r"tracking", re.I),
    re.compile(r"visitor", re.I),
    re.compile(r"user.?id", re.I),
    re.compile(r"session.?id", re.I),
    re.compile(r"fingerprint", re.I),
    re.compile(r"device.?id", re.I),
]

# ============================================================================
# Sensitive Data Purpose Patterns
# ============================================================================

SENSITIVE_PURPOSES: list[re.Pattern[str]] = [
    re.compile(r"politic|political", re.I),
    re.compile(r"health|medical", re.I),
    re.compile(r"religio", re.I),
    re.compile(r"ethnic|racial", re.I),
    re.compile(r"sexual|sex", re.I),
    re.compile(r"biometric", re.I),
    re.compile(r"genetic", re.I),
    re.compile(r"location|geo|gps", re.I),
    re.compile(r"child|minor|kid", re.I),
    re.compile(r"financial|credit|income", re.I),
]
