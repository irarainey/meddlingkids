"""Advertising tracker scoring.

Identifies advertising networks, retargeting cookies, and
real-time bidding infrastructure using table-driven name
resolution.
"""

from __future__ import annotations

import re

from src.analysis import tracker_patterns
from src.models import analysis, tracking_data
from src.utils import logger

log = logger.create_logger("Score-Advertising")


# ── Table-driven ad network name resolution ─────────────────
# Each entry maps a URL regex to a human-readable network name.
# Checked in order; the first match wins.

_AD_NETWORK_NAMES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"doubleclick|googlesyndication|googleadservices", re.I), "Google Ads"),
    (re.compile(r"facebook|fbevents", re.I), "Facebook Ads"),
    (re.compile(r"amazon-adsystem", re.I), "Amazon Ads"),
    (re.compile(r"criteo", re.I), "Criteo"),
    (re.compile(r"adnxs|appnexus", re.I), "Xandr/AppNexus"),
    (re.compile(r"taboola", re.I), "Taboola"),
    (re.compile(r"outbrain", re.I), "Outbrain"),
    (re.compile(r"thetradedesk|adsrvr", re.I), "The Trade Desk"),
    (re.compile(r"linkedin", re.I), "LinkedIn Ads"),
    (re.compile(r"twitter|ads-twitter", re.I), "Twitter Ads"),
    (re.compile(r"tiktok", re.I), "TikTok Ads"),
    (re.compile(r"pinterest", re.I), "Pinterest Ads"),
    (re.compile(r"snapchat|sc-static", re.I), "Snapchat Ads"),
]


def _resolve_network_name(url: str) -> str:
    """Resolve a URL to a human-readable ad network name.

    Falls back to the hostname when no known network matches.

    Args:
        url: The full URL that matched an advertising pattern.

    Returns:
        Human-readable network name or hostname.
    """
    for pattern, name in _AD_NETWORK_NAMES:
        if pattern.search(url):
            return name
    m = re.search(r"https?://([^/]+)", url)
    return m.group(1) if m else "Unknown ad network"


# ── Scoring ─────────────────────────────────────────────────


def calculate(
    scripts: list[tracking_data.TrackedScript],
    network_requests: list[tracking_data.NetworkRequest],
    cookies: list[tracking_data.TrackedCookie],
    all_urls: list[str],
) -> analysis.CategoryScore:
    """Score advertising tracker presence.

    Assesses the number and identity of advertising networks,
    retargeting cookie presence, and real-time bidding
    infrastructure.

    Args:
        scripts: All captured scripts.
        network_requests: All captured network requests.
        cookies: All captured cookies.
        all_urls: Combined script + request URLs.

    Returns:
        CategoryScore with uncapped raw points.
    """
    issues: list[str] = []
    points = 0

    log.debug("Advertising scoring input", data={
        "scripts": len(scripts),
        "network_requests": len(network_requests),
        "cookies": len(cookies),
        "all_urls": len(all_urls),
    })

    ad_networks: set[str] = set()
    for url in all_urls:
        for pattern in tracker_patterns.ADVERTISING_TRACKERS:
            if pattern.search(url):
                ad_networks.add(_resolve_network_name(url))
                break

    log.debug("Ad network detection", data={
        "ad_networks": list(ad_networks),
    })

    # ── Network count ───────────────────────────────────────
    if len(ad_networks) > 6:
        points += 12
        names = ", ".join(list(ad_networks)[:5])
        issues.append(
            f"{len(ad_networks)} advertising networks:"
            f" {names}..."
        )
    elif len(ad_networks) > 3:
        points += 8
        issues.append(
            f"{len(ad_networks)} ad networks:"
            f" {', '.join(ad_networks)}"
        )
    elif len(ad_networks) > 1:
        points += 5
        issues.append(
            f"{len(ad_networks)} ad networks:"
            f" {', '.join(ad_networks)}"
        )
    elif len(ad_networks) > 0:
        points += 3
        issues.append(
            f"Ad network detected:"
            f" {next(iter(ad_networks))}"
        )

    # ── Retargeting ─────────────────────────────────────────
    retargeting = [
        c
        for c in cookies
        if re.search(r"criteo|adroll|retarget", c.name, re.I)
        or re.search(r"criteo|adroll", c.domain, re.I)
    ]
    if retargeting:
        points += 4
        log.debug("Retargeting cookies found", data={
            "count": len(retargeting),
        })
        issues.append(
            "Retargeting cookies present (ads follow you)"
        )

    # ── Real-time bidding ───────────────────────────────────
    bidding = [
        url
        for url in all_urls
        if re.search(
            r"prebid|bidswitch|openx|pubmatic|magnite"
            r"|rubicon|indexexchange|casalemedia",
            url,
            re.I,
        )
    ]
    if bidding:
        points += 4
        log.debug("RTB infrastructure detected", data={
            "bidding_urls": len(bidding),
        })
        issues.append("Real-time ad bidding detected")

    log.info("Advertising score", data={
        "points": points,
        "max_points": 20,
        "issue_count": len(issues),
    })

    return analysis.CategoryScore(
        points=points, max_points=20, issues=issues
    )
