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

# ── Consent-state cookie patterns ───────────────────────────
# Cookies set by Consent Management Platforms (CMPs) to store
# user privacy preferences.  These are NOT tracking cookies and
# should be distinguished from tracking cookies in analysis.
# Their presence indicates a site is using a consent mechanism.

CONSENT_STATE_COOKIE_PATTERNS: list[re.Pattern[str]] = [
    # IAB TCF
    re.compile(r"^euconsent", re.I),
    re.compile(r"^addtl_consent$", re.I),
    # US Privacy / CCPA
    re.compile(r"^usprivacy$", re.I),
    # OneTrust
    re.compile(r"^OptanonConsent$", re.I),
    re.compile(r"^OptanonAlertBoxClosed$", re.I),
    # Cookiebot
    re.compile(r"^CookieConsent$", re.I),
    # Didomi
    re.compile(r"^didomi", re.I),
    # Complianz (WordPress)
    re.compile(r"^cmplz_", re.I),
    # Generic CMP
    re.compile(r"^__cmpcc$", re.I),
    # Cookie Law Info (WordPress)
    re.compile(r"^cookielawinfo", re.I),
    # Sourcepoint
    re.compile(r"^sp_consent$", re.I),
    re.compile(r"^consentUUID$", re.I),
    # TrustArc
    re.compile(r"^truste\.", re.I),
    re.compile(r"^notice_behavior$", re.I),
    re.compile(r"^notice_preferences$", re.I),
    # Yahoo/Oath
    re.compile(r"^CONSENTMGR$", re.I),
    # Google
    re.compile(r"^SOCS$", re.I),
    # Global Privacy Control
    re.compile(r"^GPC_SIGNAL$", re.I),
]

# ============================================================================
# Sub-category Patterns (subsets of HIGH_RISK_TRACKERS)
# ============================================================================

SESSION_REPLAY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"hotjar", re.I),
    re.compile(r"fullstory", re.I),
    re.compile(r"logrocket", re.I),
    re.compile(r"clarity\.ms", re.I),
    re.compile(r"mouseflow", re.I),
    re.compile(r"smartlook", re.I),
    re.compile(r"luckyorange", re.I),
    re.compile(r"inspectlet", re.I),
]

CROSS_DEVICE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"liveramp", re.I),
    re.compile(r"tapad", re.I),
    re.compile(r"drawbridge", re.I),
    re.compile(r"unified.?id", re.I),
    re.compile(r"id5", re.I),
    re.compile(r"thetradedesk", re.I),
    re.compile(r"lotame", re.I),
    re.compile(r"zeotap", re.I),
]

# ── Behavioural / engagement tracking ───────────────────────
# Services and scripts that track granular user behaviour
# beyond simple page views: scroll depth, mouse/eye movement,
# video engagement, attention metrics, heatmaps, rage clicks.

BEHAVIOURAL_TRACKING_PATTERNS: list[re.Pattern[str]] = [
    # Scroll & attention tracking
    re.compile(r"scroll.?depth|scroll.?track|scroll.?map", re.I),
    re.compile(r"attention.?track|attention.?metric|attention.?insight", re.I),
    re.compile(r"viewability|in.?view.?track", re.I),
    re.compile(r"time.?on.?page|dwell.?time|engaged.?time", re.I),
    # Video engagement
    re.compile(r"video.?track|video.?metric|video.?analytics", re.I),
    re.compile(r"conviva", re.I),
    re.compile(r"mux\.com|mux.?data", re.I),
    re.compile(r"youbora|npaw\.com", re.I),
    re.compile(r"vidoomy|teads", re.I),
    re.compile(r"jwplayer.*analytics|brightcove.*analytics", re.I),
    # Mouse / cursor tracking (beyond session replay)
    re.compile(r"mouse.?track|cursor.?track|click.?map", re.I),
    re.compile(r"heatmap|heat.?map", re.I),
    re.compile(r"crazy.?egg", re.I),
    re.compile(r"clicktale", re.I),
    re.compile(r"contentsquare|content.?square", re.I),
    re.compile(r"decibel.?insight|decibel\.com", re.I),
    re.compile(r"glassbox", re.I),
    re.compile(r"quantum.?metric|quantummetric", re.I),
    re.compile(r"heap\.io|heapanalytics", re.I),
    # Eye / gaze tracking
    re.compile(r"eye.?track|gaze.?track|attention.?web", re.I),
    re.compile(r"tobii|realeye|sticky\.ai", re.I),
    re.compile(r"lumen.?research|lumen.?eye", re.I),
    # Rage / frustration / error clicks
    re.compile(r"rage.?click|frustrat|dead.?click|error.?click", re.I),
]

# ── Granular location / ISP tracking ────────────────────────
# Services that resolve IP addresses to physical location,
# postcode, broadband provider, or connection type — well
# beyond simple country-level geo.

LOCATION_ISP_PATTERNS: list[re.Pattern[str]] = [
    # IP-to-location / geolocation APIs
    re.compile(r"ip.?info|ipify|ipapi|ipstack|ipdata", re.I),
    re.compile(r"ip.?geolocation|geo.?ip|geoip", re.I),
    re.compile(r"maxmind|geolite|geoip2", re.I),
    re.compile(r"ip2location|ip2proxy", re.I),
    re.compile(r"abstractapi.*ip|ipregistry", re.I),
    re.compile(r"bigdatacloud|extreme.?ip", re.I),
    # ISP / broadband provider detection
    re.compile(r"isp.?detect|isp.?lookup|whois.?api", re.I),
    re.compile(r"network.?info|net.?info|connection.?type", re.I),
    # Postcode / zip code geo-targeting
    re.compile(r"post.?code|postcode|zip.?code", re.I),
    re.compile(r"geo.?target|geo.?fence|geo.?zone", re.I),
    re.compile(r"local.?iq|yext|geo.?edge|fastly.?geo", re.I),
    # GPS / precise location
    re.compile(r"navigator\.geolocation|getCurrentPosition", re.I),
    re.compile(r"precise.?location|exact.?location", re.I),
    re.compile(r"foursquare|factual.?engine|safegraph", re.I),
]

# ── Sensitive content / topic profiling ─────────────────────
# Services and URL patterns that indicate profiling users by
# the content topics they consume — health, politics, finance,
# etc. — which can be weaponised for manipulation or
# discrimination.

CONTENT_PROFILING_PATTERNS: list[re.Pattern[str]] = [
    # Topic / interest categorisation services
    re.compile(r"grapeshot|oracle.*context|contextual.?target", re.I),
    re.compile(r"peer39|comscore.*topic|iab.?categor", re.I),
    re.compile(r"integral.?ad.?science|ias.?topic", re.I),
    re.compile(r"double.?verify|dv.?topic|dvtag", re.I),
    re.compile(r"proximic|comscore\.com", re.I),
    # Audience segmentation / DMP
    re.compile(r"audience.?segment|user.?segment", re.I),
    re.compile(r"krux|salesforce.?dmp", re.I),
    re.compile(r"permutive", re.I),
    re.compile(r"blueconic|bluekai", re.I),
    re.compile(r"bombora|intent.?data", re.I),
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
    re.compile(r"health|medical|pharma|wellness", re.I),
    re.compile(r"religio", re.I),
    re.compile(r"ethnic|racial", re.I),
    re.compile(r"sexual|sex", re.I),
    re.compile(r"biometric", re.I),
    re.compile(r"genetic", re.I),
    re.compile(r"location|geo|gps|postcode|zip.?code", re.I),
    re.compile(r"child|minor|kid", re.I),
    re.compile(r"financial|credit|income|debt|mortgage", re.I),
    re.compile(r"addiction|gambling|alcohol|substance", re.I),
    re.compile(r"mental.?health|depression|anxiety", re.I),
    re.compile(r"pregnan|fertility|baby", re.I),
    re.compile(r"criminal|arrest|conviction", re.I),
    re.compile(r"immigration|visa|asylum", re.I),
    re.compile(r"trade.?union|union.?member", re.I),
    re.compile(r"disabilit|handicap", re.I),
    re.compile(r"legal.?aid|solicitor|lawyer", re.I),
]


# ============================================================================
# Combined Alternation Patterns (pre-compiled for hot-path matching)
# ============================================================================
# Instead of iterating over ~80 individual patterns per URL,
# these combined regexes merge all per-category patterns into a
# single alternation.  This lets the regex engine match in a
# single pass, significantly reducing per-item overhead in
# build_pre_consent_stats() where we test every cookie, script,
# and request against the pattern lists.


def _combine(patterns: list[re.Pattern[str]]) -> re.Pattern[str]:
    """Merge a list of compiled patterns into one alternation regex."""
    combined = "|".join(f"(?:{p.pattern})" for p in patterns)
    # All source patterns use re.I; honour that globally.
    return re.compile(combined, re.IGNORECASE)


TRACKING_COOKIE_COMBINED: re.Pattern[str] = _combine(TRACKING_COOKIE_PATTERNS)

CONSENT_STATE_COOKIE_COMBINED: re.Pattern[str] = _combine(CONSENT_STATE_COOKIE_PATTERNS)

ALL_URL_TRACKERS_COMBINED: re.Pattern[str] = _combine(
    HIGH_RISK_TRACKERS + ADVERTISING_TRACKERS + SOCIAL_MEDIA_TRACKERS + ANALYTICS_TRACKERS
)

# ============================================================================
# TCF / Consent Framework Detection
# ============================================================================

TCF_INDICATORS: list[re.Pattern[str]] = [
    re.compile(r"__tcfapi", re.I),
    re.compile(r"euconsent", re.I),
    re.compile(r"tcf.*consent|consent.*tcf", re.I),
    re.compile(r"iab.*vendor|vendor.*iab", re.I),
    re.compile(r"transparencyandconsent|transparency.?consent", re.I),
    re.compile(r"cmpapi|__cmp\b", re.I),
    re.compile(r"gdpr.?consent|consent.?gdpr", re.I),
]

TCF_INDICATORS_COMBINED: re.Pattern[str] = _combine(TCF_INDICATORS)
