"""
Deterministic privacy score calculation.
Score ranges from 0 (best privacy) to 100 (worst privacy).

Major scoring factors:
- Number of data sharing partners (heavily weighted)
- Partner risk classification (data brokers score highest)
- Cross-site/cross-device tracking presence
- Tracking before consent is given
"""

from __future__ import annotations

import re
import time

from src.data.loader import get_tracking_scripts
from src.services.partner_classification import get_partner_risk_summary
from src.types.tracking import (
    CategoryScore,
    ConsentDetails,
    NetworkRequest,
    ScoreBreakdown,
    StorageItem,
    TrackedCookie,
    TrackedScript,
)
from src.utils.logger import create_logger

log = create_logger("PrivacyScore")


# ============================================================================
# Known Tracker Classifications
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


# ============================================================================
# Helper to extract base domain
# ============================================================================

_TWO_PART_TLDS = frozenset([
    "co.uk", "com.au", "co.nz", "co.jp", "com.br",
    "co.in", "org.uk", "net.uk", "gov.uk",
])


def _parse_domain(url: str) -> tuple[str, str]:
    """Return (site_hostname, base_domain) for URL."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = re.sub(r"^www\.", "", parsed.hostname or "").lower()
        parts = hostname.split(".")
        if len(parts) >= 2:
            last_two = ".".join(parts[-2:])
            if last_two in _TWO_PART_TLDS and len(parts) >= 3:
                base = ".".join(parts[-3:])
            else:
                base = last_two
        else:
            base = hostname
        return hostname, base
    except Exception:
        return url, url


# ============================================================================
# Scoring Functions
# ============================================================================

def calculate_privacy_score(
    cookies: list[TrackedCookie],
    scripts: list[TrackedScript],
    network_requests: list[NetworkRequest],
    local_storage: list[StorageItem],
    session_storage: list[StorageItem],
    analyzed_url: str,
    consent_details: ConsentDetails | None = None,
) -> ScoreBreakdown:
    """Calculate the complete privacy score breakdown."""
    log.info("Calculating privacy score", {
        "cookies": len(cookies),
        "scripts": len(scripts),
        "requests": len(network_requests),
    })

    site_hostname, base_domain = _parse_domain(analyzed_url)

    cookie_score = _calculate_cookie_score(cookies, base_domain)
    third_party_score = _calculate_third_party_score(network_requests, scripts, base_domain)
    data_collection_score = _calculate_data_collection_score(local_storage, session_storage, network_requests)
    fingerprint_score = _calculate_fingerprint_score(cookies, scripts, network_requests)
    advertising_score = _calculate_advertising_score(scripts, network_requests, cookies)
    social_media_score = _calculate_social_media_score(scripts, network_requests)
    sensitive_data_score = _calculate_sensitive_data_score(consent_details, scripts, network_requests)
    consent_score = _calculate_consent_score(consent_details, cookies, scripts)

    raw_total = (
        cookie_score.points
        + third_party_score.points
        + data_collection_score.points
        + fingerprint_score.points
        + advertising_score.points
        + social_media_score.points
        + sensitive_data_score.points
        + consent_score.points
    )
    total_score = min(100, round(raw_total))

    # Collect factors
    factors: list[str] = []
    if consent_score.issues:
        factors.extend(consent_score.issues[:2])
    if fingerprint_score.issues:
        factors.extend(fingerprint_score.issues[:2])
    if third_party_score.issues:
        factors.extend(third_party_score.issues[:2])
    if advertising_score.issues:
        factors.extend(advertising_score.issues[:1])
    if cookie_score.issues:
        factors.extend(cookie_score.issues[:1])
    if social_media_score.issues:
        factors.extend(social_media_score.issues[:1])
    if sensitive_data_score.issues:
        factors.extend(sensitive_data_score.issues[:1])

    summary = _generate_summary(site_hostname, total_score, factors)

    log.success("Privacy score calculated", {
        "totalScore": total_score,
        "cookies": cookie_score.points,
        "thirdParty": third_party_score.points,
        "dataCollection": data_collection_score.points,
        "fingerprinting": fingerprint_score.points,
        "advertising": advertising_score.points,
        "socialMedia": social_media_score.points,
        "sensitiveData": sensitive_data_score.points,
        "consent": consent_score.points,
    })

    for name, cat in [
        ("cookies", cookie_score),
        ("thirdParty", third_party_score),
        ("dataCollection", data_collection_score),
        ("fingerprinting", fingerprint_score),
        ("advertising", advertising_score),
        ("socialMedia", social_media_score),
        ("sensitiveData", sensitive_data_score),
        ("consent", consent_score),
    ]:
        if cat.issues:
            log.info(f"Score detail [{name}]", {"points": cat.points, "max": cat.max_points, "issues": cat.issues})

    return ScoreBreakdown(
        total_score=total_score,
        categories={
            "cookies": cookie_score,
            "thirdPartyTrackers": third_party_score,
            "dataCollection": data_collection_score,
            "fingerprinting": fingerprint_score,
            "advertising": advertising_score,
            "socialMedia": social_media_score,
            "sensitiveData": sensitive_data_score,
            "consent": consent_score,
        },
        factors=factors,
        summary=summary,
    )


def _calculate_cookie_score(cookies: list[TrackedCookie], base_domain: str) -> CategoryScore:
    """Calculate cookie-related privacy score. Max 15 points."""
    issues: list[str] = []
    points = 0

    now = time.time()

    third_party_cookies = [
        c for c in cookies
        if not c.domain.lstrip(".").endswith(base_domain)
    ]
    tracking_cookies = [
        c for c in cookies
        if any(p.search(c.name) for p in TRACKING_COOKIE_PATTERNS)
    ]
    long_lived_cookies = [
        c for c in cookies
        if c.expires > 0 and (c.expires - now) > 365 * 24 * 60 * 60
    ]

    if len(cookies) > 30:
        points += 5
        issues.append(f"{len(cookies)} cookies set (heavy tracking)")
    elif len(cookies) > 15:
        points += 4
        issues.append(f"{len(cookies)} cookies set")
    elif len(cookies) > 5:
        points += 2

    if len(third_party_cookies) > 5:
        points += 5
        issues.append(f"{len(third_party_cookies)} third-party cookies")
    elif len(third_party_cookies) > 2:
        points += 3
        issues.append(f"{len(third_party_cookies)} third-party cookies")
    elif len(third_party_cookies) > 0:
        points += 2

    if len(tracking_cookies) > 3:
        points += 5
        issues.append(f"{len(tracking_cookies)} known tracking cookies")
    elif len(tracking_cookies) > 0:
        points += 3
        issues.append(f"{len(tracking_cookies)} tracking cookies detected")

    if len(long_lived_cookies) > 3:
        points += 2
        issues.append(f"{len(long_lived_cookies)} cookies persist over 1 year")
    elif len(long_lived_cookies) > 0:
        points += 1

    return CategoryScore(points=min(15, points), max_points=15, issues=issues)


def _calculate_third_party_score(
    network_requests: list[NetworkRequest],
    scripts: list[TrackedScript],
    base_domain: str,
) -> CategoryScore:
    """Calculate third-party tracker score. Max 20 points."""
    issues: list[str] = []
    points = 0

    third_party_domains: set[str] = set()
    for req in network_requests:
        if req.is_third_party:
            third_party_domains.add(req.domain)
    for script in scripts:
        if not script.domain.endswith(base_domain):
            third_party_domains.add(script.domain)

    third_party_requests = [r for r in network_requests if r.is_third_party]

    known_trackers: set[str] = set()
    all_urls = [s.url for s in scripts] + [r.url for r in network_requests]
    tracking_scripts = get_tracking_scripts()
    for url in all_urls:
        for ts in tracking_scripts:
            if re.search(ts.pattern, url, re.IGNORECASE):
                m = re.search(r"https?://([^/]+)", url)
                if m:
                    known_trackers.add(m.group(1))
                break

    if len(third_party_domains) > 20:
        points += 10
        issues.append(f"{len(third_party_domains)} third-party domains contacted")
    elif len(third_party_domains) > 10:
        points += 7
        issues.append(f"{len(third_party_domains)} third-party domains")
    elif len(third_party_domains) > 5:
        points += 5
        issues.append(f"{len(third_party_domains)} third-party domains")
    elif len(third_party_domains) > 0:
        points += 3

    if len(third_party_requests) > 100:
        points += 5
        issues.append(f"{len(third_party_requests)} third-party requests")
    elif len(third_party_requests) > 50:
        points += 3
    elif len(third_party_requests) > 20:
        points += 2

    if len(known_trackers) > 8:
        points += 8
        issues.append(f"{len(known_trackers)} known tracking services identified")
    elif len(known_trackers) > 4:
        points += 6
        issues.append(f"{len(known_trackers)} known tracking services")
    elif len(known_trackers) > 1:
        points += 4
        issues.append(f"{len(known_trackers)} known trackers")
    elif len(known_trackers) > 0:
        points += 2

    return CategoryScore(points=min(20, points), max_points=20, issues=issues)


def _calculate_data_collection_score(
    local_storage: list[StorageItem],
    session_storage: list[StorageItem],
    network_requests: list[NetworkRequest],
) -> CategoryScore:
    """Calculate data collection score. Max 10 points."""
    issues: list[str] = []
    points = 0

    tracking_storage = [
        item for item in local_storage
        if any(p.search(item.key) for p in TRACKING_STORAGE_PATTERNS)
    ]
    beacon_requests = [
        r for r in network_requests
        if r.resource_type == "image" and r.is_third_party and len(r.url) > 200
    ]
    third_party_posts = [
        r for r in network_requests
        if r.method == "POST" and r.is_third_party
    ]
    analytics_urls = [
        r for r in network_requests
        if any(p.search(r.url) for p in ANALYTICS_TRACKERS)
    ]

    if len(local_storage) > 15:
        points += 3
        issues.append(f"{len(local_storage)} localStorage items (extensive data storage)")
    elif len(local_storage) > 5:
        points += 2

    if len(tracking_storage) > 0:
        points += 3
        issues.append(f"{len(tracking_storage)} tracking-related storage items")

    if len(beacon_requests) > 10:
        points += 4
        issues.append(f"{len(beacon_requests)} tracking beacons/pixels detected")
    elif len(beacon_requests) > 3:
        points += 2

    if len(third_party_posts) > 5:
        points += 3
        issues.append(f"{len(third_party_posts)} data submissions to third parties")
    elif len(third_party_posts) > 0:
        points += 1

    if len(analytics_urls) > 0:
        points += 2
        issues.append("Analytics tracking active")

    return CategoryScore(points=min(10, points), max_points=10, issues=issues)


def _calculate_fingerprint_score(
    cookies: list[TrackedCookie],
    scripts: list[TrackedScript],
    network_requests: list[NetworkRequest],
) -> CategoryScore:
    """Calculate fingerprinting score. Max 20 points."""
    issues: list[str] = []
    points = 0

    all_urls = [s.url for s in scripts] + [r.url for r in network_requests]

    fingerprint_services: list[str] = []
    for url in all_urls:
        for pattern in HIGH_RISK_TRACKERS:
            if pattern.search(url):
                m = re.search(r"https?://([^/]+)", url)
                if m and m.group(1) not in fingerprint_services:
                    fingerprint_services.append(m.group(1))

    session_replay_patterns = [
        re.compile(r"hotjar", re.I), re.compile(r"fullstory", re.I),
        re.compile(r"logrocket", re.I), re.compile(r"clarity\.ms", re.I),
        re.compile(r"mouseflow", re.I), re.compile(r"smartlook", re.I),
        re.compile(r"luckyorange", re.I), re.compile(r"inspectlet", re.I),
    ]
    session_replay_services = [
        s for s in fingerprint_services
        if any(p.search(s) for p in session_replay_patterns)
    ]

    cross_device_patterns = [
        re.compile(r"liveramp", re.I), re.compile(r"tapad", re.I),
        re.compile(r"drawbridge", re.I), re.compile(r"unified.?id", re.I),
        re.compile(r"id5", re.I), re.compile(r"thetradedesk", re.I),
        re.compile(r"lotame", re.I), re.compile(r"zeotap", re.I),
    ]
    cross_device_trackers = [
        url for url in all_urls
        if any(p.search(url) for p in cross_device_patterns)
    ]

    fingerprint_cookies = [
        c for c in cookies
        if any(p.search(c.name) for p in FINGERPRINT_COOKIE_PATTERNS)
    ]

    if len(session_replay_services) > 1:
        points += 12
        issues.append(f"Multiple session replay tools ({', '.join(session_replay_services)}) - your interactions are recorded")
    elif len(session_replay_services) > 0:
        points += 10
        issues.append(f"Session replay active ({session_replay_services[0]}) - your mouse movements and clicks are recorded")

    if len(cross_device_trackers) > 0:
        points += 8
        issues.append("Cross-device identity tracking detected - you are tracked across all your devices")

    other_fingerprinters = len(fingerprint_services) - len(session_replay_services)
    if other_fingerprinters > 3:
        points += 6
        issues.append(f"{other_fingerprinters} fingerprinting services identified")
    elif other_fingerprinters > 0:
        points += 4
        issues.append(f"{other_fingerprinters} fingerprinting/tracking services")

    if len(fingerprint_cookies) > 0:
        points += 3
        issues.append(f"{len(fingerprint_cookies)} fingerprint-related cookies")

    return CategoryScore(points=min(20, points), max_points=20, issues=issues)


def _calculate_advertising_score(
    scripts: list[TrackedScript],
    network_requests: list[NetworkRequest],
    cookies: list[TrackedCookie],
) -> CategoryScore:
    """Calculate advertising tracker score. Max 15 points."""
    issues: list[str] = []
    points = 0
    all_urls = [s.url for s in scripts] + [r.url for r in network_requests]

    ad_networks: set[str] = set()
    for url in all_urls:
        for pattern in ADVERTISING_TRACKERS:
            if pattern.search(url):
                if re.search(r"doubleclick|googlesyndication|googleadservices", url, re.I):
                    ad_networks.add("Google Ads")
                elif re.search(r"facebook|fbevents", url, re.I):
                    ad_networks.add("Facebook Ads")
                elif re.search(r"amazon-adsystem", url, re.I):
                    ad_networks.add("Amazon Ads")
                elif re.search(r"criteo", url, re.I):
                    ad_networks.add("Criteo")
                elif re.search(r"adnxs|appnexus", url, re.I):
                    ad_networks.add("Xandr/AppNexus")
                elif re.search(r"taboola", url, re.I):
                    ad_networks.add("Taboola")
                elif re.search(r"outbrain", url, re.I):
                    ad_networks.add("Outbrain")
                elif re.search(r"thetradedesk|adsrvr", url, re.I):
                    ad_networks.add("The Trade Desk")
                elif re.search(r"linkedin", url, re.I):
                    ad_networks.add("LinkedIn Ads")
                elif re.search(r"twitter|ads-twitter", url, re.I):
                    ad_networks.add("Twitter Ads")
                elif re.search(r"tiktok", url, re.I):
                    ad_networks.add("TikTok Ads")
                elif re.search(r"pinterest", url, re.I):
                    ad_networks.add("Pinterest Ads")
                elif re.search(r"snapchat|sc-static", url, re.I):
                    ad_networks.add("Snapchat Ads")
                else:
                    m = re.search(r"https?://([^/]+)", url)
                    if m:
                        ad_networks.add(m.group(1))
                break

    if len(ad_networks) > 6:
        points += 12
        names = ", ".join(list(ad_networks)[:5])
        issues.append(f"{len(ad_networks)} advertising networks: {names}...")
    elif len(ad_networks) > 3:
        points += 8
        issues.append(f"{len(ad_networks)} ad networks: {', '.join(ad_networks)}")
    elif len(ad_networks) > 1:
        points += 5
        issues.append(f"{len(ad_networks)} ad networks: {', '.join(ad_networks)}")
    elif len(ad_networks) > 0:
        points += 3
        issues.append(f"Ad network detected: {list(ad_networks)[0]}")

    retargeting_cookies = [
        c for c in cookies
        if re.search(r"criteo|adroll|retarget", c.name, re.I)
        or re.search(r"criteo|adroll", c.domain, re.I)
    ]
    if retargeting_cookies:
        points += 4
        issues.append("Retargeting cookies present (ads follow you)")

    bidding_indicators = [
        url for url in all_urls
        if re.search(r"prebid|bidswitch|openx|pubmatic|magnite|rubicon|indexexchange|casalemedia", url, re.I)
    ]
    if bidding_indicators:
        points += 4
        issues.append("Real-time ad bidding detected")

    return CategoryScore(points=min(15, points), max_points=15, issues=issues)


def _calculate_social_media_score(
    scripts: list[TrackedScript],
    network_requests: list[NetworkRequest],
) -> CategoryScore:
    """Calculate social media tracker score. Max 10 points."""
    issues: list[str] = []
    points = 0
    all_urls = [s.url for s in scripts] + [r.url for r in network_requests]

    social_trackers: set[str] = set()
    for url in all_urls:
        for pattern in SOCIAL_MEDIA_TRACKERS:
            if pattern.search(url):
                if re.search(r"facebook|fbcdn", url, re.I):
                    social_trackers.add("Facebook")
                elif re.search(r"twitter", url, re.I):
                    social_trackers.add("Twitter/X")
                elif re.search(r"linkedin", url, re.I):
                    social_trackers.add("LinkedIn")
                elif re.search(r"pinterest", url, re.I):
                    social_trackers.add("Pinterest")
                elif re.search(r"tiktok", url, re.I):
                    social_trackers.add("TikTok")
                elif re.search(r"instagram", url, re.I):
                    social_trackers.add("Instagram")
                elif re.search(r"snapchat", url, re.I):
                    social_trackers.add("Snapchat")
                elif re.search(r"reddit", url, re.I):
                    social_trackers.add("Reddit")
                elif re.search(r"addthis|sharethis|addtoany", url, re.I):
                    social_trackers.add("Social sharing widgets")
                break

    if len(social_trackers) > 3:
        points += 10
        issues.append(f"{len(social_trackers)} social media trackers: {', '.join(social_trackers)}")
    elif len(social_trackers) > 1:
        points += 6
        issues.append(f"Social media tracking: {', '.join(social_trackers)}")
    elif len(social_trackers) > 0:
        points += 4
        issues.append(f"{', '.join(social_trackers)} tracking present")

    social_plugins = [
        url for url in all_urls
        if re.search(r"platform\.(twitter|facebook|linkedin)|widgets\.(twitter|facebook)", url, re.I)
    ]
    if social_plugins:
        points += 3
        issues.append("Social media plugins embedded (tracks even without interaction)")

    return CategoryScore(points=min(10, points), max_points=10, issues=issues)


def _calculate_sensitive_data_score(
    consent_details: ConsentDetails | None,
    scripts: list[TrackedScript],
    network_requests: list[NetworkRequest],
) -> CategoryScore:
    """Calculate sensitive data tracking score. Max 10 points."""
    issues: list[str] = []
    points = 0

    if consent_details:
        all_purposes = " ".join([
            *consent_details.purposes,
            *[c.description for c in consent_details.categories],
            consent_details.raw_text or "",
        ])
        for p in SENSITIVE_PURPOSES:
            if p.search(all_purposes):
                points += 2
                src = p.pattern
                if re.search(r"location|geo|gps", src, re.I):
                    issues.append("Location data collection disclosed")
                elif re.search(r"politic", src, re.I):
                    issues.append("Political interest tracking disclosed")
                elif re.search(r"health|medical", src, re.I):
                    issues.append("Health-related data collection disclosed")
                elif re.search(r"financial|credit", src, re.I):
                    issues.append("Financial data tracking disclosed")
                break

    all_urls = [s.url for s in scripts] + [r.url for r in network_requests]
    if any(re.search(r"geo|location|ip.?info|ipify|ipapi", url, re.I) for url in all_urls):
        points += 3
        issues.append("Geolocation/IP tracking detected")

    if any(re.search(r"liveramp|unified.?id|id5|lotame|thetradedesk.*unified", url, re.I) for url in all_urls):
        points += 4
        issues.append("Cross-site identity tracking (identity resolution service)")

    return CategoryScore(points=min(10, points), max_points=10, issues=issues)


def _calculate_consent_score(
    consent_details: ConsentDetails | None,
    cookies: list[TrackedCookie],
    scripts: list[TrackedScript],
) -> CategoryScore:
    """Calculate consent-related issues score. Max 25 points."""
    issues: list[str] = []
    points = 0

    tracking_patterns = get_tracking_scripts()
    tracking_scripts = [
        s for s in scripts
        if any(re.search(t.pattern, s.url, re.IGNORECASE) for t in tracking_patterns)
    ]

    if len(tracking_scripts) > 5:
        points += 10
        issues.append(f"{len(tracking_scripts)} tracking scripts loaded BEFORE consent given (violation)")
    elif len(tracking_scripts) > 2:
        points += 7
        issues.append(f"{len(tracking_scripts)} tracking scripts loaded before consent")
    elif len(tracking_scripts) > 0:
        points += 4
        issues.append("Tracking active before consent given")

    if not consent_details:
        has_tracking = len(cookies) > 5 or len(tracking_scripts) > 0
        if has_tracking:
            points += 8
            issues.append("Tracking present without visible consent dialog")
        return CategoryScore(points=min(25, points), max_points=25, issues=issues)

    partner_count = len(consent_details.partners)

    if partner_count > 500:
        points += 15
        issues.append(f"{partner_count} partners share your data (extreme)")
    elif partner_count > 300:
        points += 12
        issues.append(f"{partner_count} partners share your data (massive)")
    elif partner_count > 150:
        points += 10
        issues.append(f"{partner_count} partners share your data (excessive)")
    elif partner_count > 75:
        points += 8
        issues.append(f"{partner_count} partners share your data")
    elif partner_count > 30:
        points += 6
        issues.append(f"{partner_count} data sharing partners")
    elif partner_count > 10:
        points += 4
        issues.append(f"{partner_count} data sharing partners")
    elif partner_count > 0:
        points += 2

    if partner_count > 0:
        risk_summary = get_partner_risk_summary(consent_details.partners)
        critical_count = risk_summary["critical_count"]
        high_count = risk_summary["high_count"]
        worst_partners = risk_summary["worst_partners"]

        if critical_count > 5:  # type: ignore[operator]
            points += 8
            issues.append(f"{critical_count} data brokers/identity trackers identified")
        elif critical_count > 2:  # type: ignore[operator]
            points += 5
            issues.append(f"{critical_count} data brokers among partners")
        elif critical_count > 0:  # type: ignore[operator]
            points += 3
            issues.append(f"Data broker detected: {worst_partners[0]}")  # type: ignore[index]

        if high_count > 10:  # type: ignore[operator]
            points += 5
            issues.append(f"{high_count} high-risk advertising/tracking partners")
        elif high_count > 5:  # type: ignore[operator]
            points += 3
        elif high_count > 0:  # type: ignore[operator]
            points += 2

    vague_re = re.compile(r"legitimate interest|necessary|essential|basic|functional", re.I)
    vague_purposes = [p for p in consent_details.purposes if vague_re.search(p)]
    if len(vague_purposes) > 2:
        points += 3
        issues.append("Consent uses vague terms to justify tracking")

    return CategoryScore(points=min(25, points), max_points=25, issues=issues)


def _generate_summary(site_name: str, score: int, factors: list[str]) -> str:
    """Generate a human-readable summary sentence."""
    if score >= 80:
        severity = "extensive"
        description = "with aggressive cross-site tracking and data sharing"
    elif score >= 60:
        severity = "significant"
        description = "with multiple advertising networks and third-party trackers"
    elif score >= 40:
        severity = "moderate"
        description = "with standard analytics and some advertising trackers"
    elif score >= 20:
        severity = "limited"
        description = "with basic analytics and minimal third-party presence"
    else:
        severity = "minimal"
        description = "with privacy-respecting practices"

    top_factor = (factors[0] if factors else "").lower()
    if "session replay" in top_factor:
        description = "including session recording that captures your interactions"
    elif "fingerprint" in top_factor:
        description = "including device fingerprinting for cross-site tracking"
    elif "ad network" in top_factor:
        description = f"including {top_factor}"

    return f"{site_name} has {severity} tracking {description}."
