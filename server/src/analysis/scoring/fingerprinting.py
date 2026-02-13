"""Fingerprinting, behavioural, and advanced tracking scoring.

Evaluates session-replay tools, cross-device identity
trackers, fingerprinting services, behavioural engagement
tracking (scroll, video, heatmaps, eye tracking), and
fingerprint-related cookies.
"""

from __future__ import annotations

import re

from src.analysis import tracker_patterns
from src.models import analysis, tracking_data
from src.utils import logger

log = logger.create_logger("Score-Fingerprinting")


def calculate(
    cookies: list[tracking_data.TrackedCookie],
    scripts: list[tracking_data.TrackedScript],
    network_requests: list[tracking_data.NetworkRequest],
    all_urls: list[str],
) -> analysis.CategoryScore:
    """Score fingerprinting and advanced tracking presence.

    Assesses session-replay tools, cross-device identity
    tracking, general fingerprinting services, behavioural
    engagement tracking, and fingerprint-related cookies.

    Args:
        cookies: All captured cookies.
        scripts: All captured scripts.
        network_requests: All captured network requests.
        all_urls: Combined script + request URLs.

    Returns:
        CategoryScore with uncapped raw points.
    """
    issues: list[str] = []
    points = 0

    log.debug(
        "Fingerprinting scoring input",
        data={
            "cookies": len(cookies),
            "scripts": len(scripts),
            "network_requests": len(network_requests),
            "all_urls": len(all_urls),
        },
    )

    fingerprint_services: list[str] = []
    for url in all_urls:
        for pattern in tracker_patterns.HIGH_RISK_TRACKERS:
            if pattern.search(url):
                m = re.search(r"https?://([^/]+)", url)
                if m and m.group(1) not in fingerprint_services:
                    fingerprint_services.append(m.group(1))

    session_replay_services = [s for s in fingerprint_services if any(p.search(s) for p in tracker_patterns.SESSION_REPLAY_PATTERNS)]

    cross_device_trackers = [url for url in all_urls if any(p.search(url) for p in tracker_patterns.CROSS_DEVICE_PATTERNS)]

    fingerprint_cookies = [c for c in cookies if any(p.search(c.name) for p in tracker_patterns.FINGERPRINT_COOKIE_PATTERNS)]

    log.debug(
        "Fingerprinting detection",
        data={
            "fingerprint_services": len(fingerprint_services),
            "session_replay": len(session_replay_services),
            "cross_device": len(cross_device_trackers),
            "fingerprint_cookies": len(fingerprint_cookies),
            "services": fingerprint_services[:10],
        },
    )

    # ── Session replay ──────────────────────────────────────
    if len(session_replay_services) > 1:
        points += 12
        names = ", ".join(session_replay_services)
        issues.append(f"Multiple session replay tools ({names}) - your interactions are recorded")
    elif len(session_replay_services) > 0:
        points += 10
        issues.append(f"Session replay active ({session_replay_services[0]}) - your mouse movements and clicks are recorded")

    # ── Cross-device ────────────────────────────────────────
    if len(cross_device_trackers) > 0:
        points += 8
        issues.append("Cross-device identity tracking detected - you are tracked across all your devices")

    # ── Other fingerprinters ────────────────────────────────
    other_count = len(fingerprint_services) - len(session_replay_services)
    if other_count > 3:
        points += 6
        issues.append(f"{other_count} fingerprinting services identified")
    elif other_count > 0:
        points += 4
        issues.append(f"{other_count} fingerprinting/tracking services")

    # ── Behavioural / engagement tracking ───────────────────
    behavioural_hits = _detect_behavioural_tracking(all_urls)
    if behavioural_hits:
        points += min(10, 3 * len(behavioural_hits))
        log.debug(
            "Behavioural tracking detected",
            data={
                "categories": behavioural_hits,
                "behaviour_points": min(10, 3 * len(behavioural_hits)),
            },
        )
        for label in behavioural_hits[:3]:
            issues.append(label)

    # ── Fingerprint cookies ─────────────────────────────────
    if len(fingerprint_cookies) > 0:
        points += 3
        issues.append(f"{len(fingerprint_cookies)} fingerprint-related cookies")

    log.info(
        "Fingerprinting score",
        data={
            "points": points,
            "max_points": 39,
            "issue_count": len(issues),
        },
    )

    return analysis.CategoryScore(points=points, max_points=39, issues=issues)


# ── Behavioural tracking helpers ────────────────────────────

# Each entry maps a compiled URL pattern to a human-readable
# label.  Grouped by behaviour category so the issues list
# stays concise even for heavy sites.

_BEHAVIOUR_CATEGORIES: list[tuple[str, list[re.Pattern[str]]]] = [
    (
        "Scroll depth / attention tracking detected",
        [
            p
            for p in tracker_patterns.BEHAVIOURAL_TRACKING_PATTERNS
            if any(
                kw in p.pattern
                for kw in (
                    "scroll",
                    "attention",
                    "viewab",
                    "dwell",
                    "time.?on",
                )
            )
        ],
    ),
    (
        "Video engagement tracking detected",
        [
            p
            for p in tracker_patterns.BEHAVIOURAL_TRACKING_PATTERNS
            if any(
                kw in p.pattern
                for kw in (
                    "video",
                    "conviva",
                    "mux",
                    "youbora",
                    "npaw",
                    "vidoomy",
                    "teads",
                    "jwplayer",
                    "brightcove",
                )
            )
        ],
    ),
    (
        "Mouse / cursor heatmap tracking detected",
        [
            p
            for p in tracker_patterns.BEHAVIOURAL_TRACKING_PATTERNS
            if any(
                kw in p.pattern
                for kw in (
                    "mouse",
                    "cursor",
                    "click.?map",
                    "heatmap",
                    "heat.?map",
                    "crazy",
                    "clicktale",
                    "contentsquare",
                    "decibel",
                    "glassbox",
                    "quantum",
                    "heap",
                )
            )
        ],
    ),
    (
        "Eye / gaze tracking technology detected - monitors where you look on the page",
        [
            p
            for p in tracker_patterns.BEHAVIOURAL_TRACKING_PATTERNS
            if any(
                kw in p.pattern
                for kw in (
                    "eye",
                    "gaze",
                    "tobii",
                    "realeye",
                    "sticky",
                    "lumen",
                )
            )
        ],
    ),
    (
        "Frustration / rage-click tracking detected",
        [
            p
            for p in tracker_patterns.BEHAVIOURAL_TRACKING_PATTERNS
            if any(
                kw in p.pattern
                for kw in (
                    "rage",
                    "frustrat",
                    "dead.?click",
                    "error.?click",
                )
            )
        ],
    ),
]


def _detect_behavioural_tracking(
    all_urls: list[str],
) -> list[str]:
    """Scan URLs for behavioural tracking services.

    Returns a deduplicated list of human-readable issue
    labels, one per matched behaviour category.
    """
    matched: list[str] = []
    for label, patterns in _BEHAVIOUR_CATEGORIES:
        for url in all_urls:
            if any(p.search(url) for p in patterns):
                matched.append(label)
                break
    return matched
