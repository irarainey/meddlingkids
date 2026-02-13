"""Social media tracker scoring.

Identifies social media tracking pixels, SDKs, and embedded
plugins using table-driven name resolution.
"""

from __future__ import annotations

import re

from src.analysis import tracker_patterns
from src.models import analysis, tracking_data
from src.utils import logger

log = logger.create_logger("Score-SocialMedia")


# ── Table-driven social tracker name resolution ─────────────

_SOCIAL_TRACKER_NAMES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"facebook|fbcdn", re.I), "Facebook"),
    (re.compile(r"twitter", re.I), "Twitter/X"),
    (re.compile(r"linkedin", re.I), "LinkedIn"),
    (re.compile(r"pinterest", re.I), "Pinterest"),
    (re.compile(r"tiktok", re.I), "TikTok"),
    (re.compile(r"instagram", re.I), "Instagram"),
    (re.compile(r"snapchat", re.I), "Snapchat"),
    (re.compile(r"reddit", re.I), "Reddit"),
    (re.compile(r"addthis|sharethis|addtoany", re.I), "Social sharing widgets"),
]


def _resolve_tracker_name(url: str) -> str:
    """Resolve a URL to a human-readable social tracker name.

    Falls back to the hostname when no known tracker matches.

    Args:
        url: The full URL that matched a social media pattern.

    Returns:
        Human-readable tracker name or hostname.
    """
    for pattern, name in _SOCIAL_TRACKER_NAMES:
        if pattern.search(url):
            return name
    m = re.search(r"https?://([^/]+)", url)
    return m.group(1) if m else "Unknown social tracker"


# ── Scoring ─────────────────────────────────────────────────


def calculate(
    scripts: list[tracking_data.TrackedScript],
    network_requests: list[tracking_data.NetworkRequest],
    all_urls: list[str],
) -> analysis.CategoryScore:
    """Score social media tracker presence.

    Assesses the number of distinct social media tracking
    services and whether embedded social plugins are present.

    Args:
        scripts: All captured scripts.
        network_requests: All captured network requests.
        all_urls: Combined script + request URLs.

    Returns:
        CategoryScore with uncapped raw points.
    """
    issues: list[str] = []
    points = 0

    log.debug(
        "Social media scoring input",
        data={
            "scripts": len(scripts),
            "network_requests": len(network_requests),
            "all_urls": len(all_urls),
        },
    )

    social_trackers: set[str] = set()
    for url in all_urls:
        for pattern in tracker_patterns.SOCIAL_MEDIA_TRACKERS:
            if pattern.search(url):
                social_trackers.add(_resolve_tracker_name(url))
                break

    log.debug(
        "Social tracker detection",
        data={
            "social_trackers": list(social_trackers),
        },
    )

    # ── Tracker count ───────────────────────────────────────
    if len(social_trackers) > 3:
        points += 10
        issues.append(f"{len(social_trackers)} social media trackers: {', '.join(social_trackers)}")
    elif len(social_trackers) > 1:
        points += 6
        issues.append(f"Social media tracking: {', '.join(social_trackers)}")
    elif len(social_trackers) > 0:
        points += 4
        issues.append(f"{', '.join(social_trackers)} tracking present")

    # ── Embedded plugins ────────────────────────────────────
    social_plugins = [
        url
        for url in all_urls
        if re.search(
            r"platform\.(twitter|facebook|linkedin)"
            r"|widgets\.(twitter|facebook)",
            url,
            re.I,
        )
    ]
    if social_plugins:
        points += 3
        log.debug(
            "Social plugins embedded",
            data={
                "plugin_urls": len(social_plugins),
            },
        )
        issues.append("Social media plugins embedded (tracks even without interaction)")

    log.info(
        "Social media score",
        data={
            "points": points,
            "max_points": 13,
            "issue_count": len(issues),
        },
    )

    return analysis.CategoryScore(points=points, max_points=13, issues=issues)
