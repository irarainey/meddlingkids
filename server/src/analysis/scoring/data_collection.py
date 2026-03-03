"""Data collection scoring.

Evaluates localStorage usage, tracking beacons/pixels,
third-party POST requests, and analytics tracker presence.
"""

from __future__ import annotations

from src.analysis import tracker_patterns
from src.analysis.scoring import _tiers
from src.models import analysis, tracking_data
from src.utils import logger

log = logger.create_logger("Score-DataCollection")

# Third-party image requests with URLs longer than this are
# classified as tracking beacons / pixels.  Long query strings
# typically carry user-identification or event-telemetry data.
_BEACON_URL_LENGTH_THRESHOLD = 200

# ── Tier tables ─────────────────────────────────────────────

_STORAGE_VOLUME_TIERS: tuple[_tiers.Tier, ...] = (
    (30, 4, "{n} localStorage items (extensive)"),
    (15, 3, "{n} localStorage items (extensive data storage)"),
    (5, 2, None),
)

_BEACON_TIERS: tuple[_tiers.Tier, ...] = (
    (30, 6, "{n} tracking beacons/pixels detected (extreme)"),
    (10, 4, "{n} tracking beacons/pixels detected"),
    (3, 2, None),
)

_THIRD_PARTY_POST_TIERS: tuple[_tiers.Tier, ...] = (
    (5, 3, "{n} data submissions to third parties"),
    (0, 1, None),
)


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
    beacon_requests = [
        r for r in network_requests if r.resource_type == "image" and r.is_third_party and len(r.url) > _BEACON_URL_LENGTH_THRESHOLD
    ]
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
    pts, issue = _tiers.score_by_tiers(len(local_storage), _STORAGE_VOLUME_TIERS)
    points += pts
    if issue:
        issues.append(issue)

    # ── Tracking storage ────────────────────────────────────
    if len(tracking_storage) > 0:
        points += 3
        issues.append(f"{len(tracking_storage)} tracking-related storage items")

    # ── Beacons / pixels ────────────────────────────────────
    pts, issue = _tiers.score_by_tiers(len(beacon_requests), _BEACON_TIERS)
    points += pts
    if issue:
        issues.append(issue)

    # ── Third-party POSTs ───────────────────────────────────
    pts, issue = _tiers.score_by_tiers(len(third_party_posts), _THIRD_PARTY_POST_TIERS)
    points += pts
    if issue:
        issues.append(issue)

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
