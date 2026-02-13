"""Data collection scoring.

Evaluates localStorage usage, tracking beacons/pixels,
third-party POST requests, and analytics tracker presence.
"""

from __future__ import annotations

from src.analysis import tracker_patterns
from src.models import analysis, tracking_data
from src.utils import logger

log = logger.create_logger("Score-DataCollection")


def calculate(
    local_storage: list[tracking_data.StorageItem],
    session_storage: list[tracking_data.StorageItem],
    network_requests: list[tracking_data.NetworkRequest],
) -> analysis.CategoryScore:
    """Score data collection behaviour.

    Assesses localStorage volume, tracking-related storage
    keys, pixel/beacon request counts, third-party data
    submissions, and active analytics tracking.

    Args:
        local_storage: Captured localStorage items.
        session_storage: Captured sessionStorage items.
        network_requests: All captured network requests.

    Returns:
        CategoryScore with uncapped raw points.
    """
    issues: list[str] = []
    points = 0

    log.debug(
        "Data collection scoring input",
        data={
            "local_storage": len(local_storage),
            "session_storage": len(session_storage),
            "network_requests": len(network_requests),
        },
    )

    tracking_storage = [item for item in local_storage if any(p.search(item.key) for p in tracker_patterns.TRACKING_STORAGE_PATTERNS)]
    beacon_requests = [r for r in network_requests if r.resource_type == "image" and r.is_third_party and len(r.url) > 200]
    third_party_posts = [r for r in network_requests if r.method == "POST" and r.is_third_party]
    analytics_urls = [r for r in network_requests if any(p.search(r.url) for p in tracker_patterns.ANALYTICS_TRACKERS)]

    log.debug(
        "Data collection detection",
        data={
            "tracking_storage": len(tracking_storage),
            "beacon_requests": len(beacon_requests),
            "third_party_posts": len(third_party_posts),
            "analytics_urls": len(analytics_urls),
        },
    )

    # ── Storage volume ──────────────────────────────────────
    if len(local_storage) > 30:
        points += 4
        issues.append(f"{len(local_storage)} localStorage items (extensive)")
    elif len(local_storage) > 15:
        points += 3
        issues.append(f"{len(local_storage)} localStorage items (extensive data storage)")
    elif len(local_storage) > 5:
        points += 2

    # ── Tracking storage ────────────────────────────────────
    if len(tracking_storage) > 0:
        points += 3
        issues.append(f"{len(tracking_storage)} tracking-related storage items")

    # ── Beacons / pixels ────────────────────────────────────
    if len(beacon_requests) > 30:
        points += 6
        issues.append(f"{len(beacon_requests)} tracking beacons/pixels detected (extreme)")
    elif len(beacon_requests) > 10:
        points += 4
        issues.append(f"{len(beacon_requests)} tracking beacons/pixels detected")
    elif len(beacon_requests) > 3:
        points += 2

    # ── Third-party POSTs ───────────────────────────────────
    if len(third_party_posts) > 5:
        points += 3
        issues.append(f"{len(third_party_posts)} data submissions to third parties")
    elif len(third_party_posts) > 0:
        points += 1

    # ── Analytics ───────────────────────────────────────────
    if len(analytics_urls) > 0:
        points += 2
        issues.append("Analytics tracking active")

    log.info(
        "Data collection score",
        data={
            "points": points,
            "max_points": 18,
            "issue_count": len(issues),
        },
    )

    return analysis.CategoryScore(points=points, max_points=18, issues=issues)
