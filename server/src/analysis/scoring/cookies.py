"""Cookie-based privacy scoring.

Evaluates cookie volume, third-party cookies, known tracking
cookie patterns, and long-lived persistence to produce a
category score.
"""

from __future__ import annotations

import time

from src.analysis import tracker_patterns
from src.analysis.scoring import _tiers
from src.models import analysis, tracking_data
from src.utils import logger

log = logger.create_logger("Score-Cookies")

# ── Tier tables ─────────────────────────────────────────────

_VOLUME_TIERS: tuple[_tiers.Tier, ...] = (
    (100, 8, "{n} cookies set (extreme)"),
    (50, 6, "{n} cookies set (heavy)"),
    (30, 5, "{n} cookies set (heavy tracking)"),
    (15, 4, "{n} cookies set"),
    (5, 2, None),
)

_THIRD_PARTY_TIERS: tuple[_tiers.Tier, ...] = (
    (15, 7, "{n} third-party cookies"),
    (5, 5, "{n} third-party cookies"),
    (2, 3, "{n} third-party cookies"),
    (0, 2, None),
)

_TRACKING_COOKIE_TIERS: tuple[_tiers.Tier, ...] = (
    (3, 5, "{n} known tracking cookies"),
    (0, 3, "{n} tracking cookies detected"),
)

_PERSISTENCE_TIERS: tuple[_tiers.Tier, ...] = (
    (3, 2, "{n} cookies persist over 1 year"),
    (0, 1, None),
)


def calculate(
    cookies: list[tracking_data.TrackedCookie],
    base_domain: str,
) -> analysis.CategoryScore:
    """Score cookie-related privacy signals.

    Assesses total cookie count, third-party cookie presence,
    known tracking cookie patterns, and cookies that persist
    longer than one year.

    Args:
        cookies: All cookies captured during the session.
        base_domain: The analysed site's registrable domain.

    Returns:
        CategoryScore with uncapped raw points.
    """
    issues: list[str] = []
    points = 0
    now = time.time()

    log.debug(
        "Cookie scoring input",
        data={
            "total_cookies": len(cookies),
            "base_domain": base_domain,
        },
    )

    third_party = [c for c in cookies if not c.domain.lstrip(".").endswith(base_domain)]
    tracking = [c for c in cookies if any(p.search(c.name) for p in tracker_patterns.TRACKING_COOKIE_PATTERNS)]
    long_lived = [c for c in cookies if c.expires > 0 and (c.expires - now) > 365 * 24 * 60 * 60]

    log.debug(
        "Cookie classification",
        data={
            "third_party": len(third_party),
            "tracking": len(tracking),
            "long_lived": len(long_lived),
        },
    )

    # ── Volume ──────────────────────────────────────────────
    pts, issue = _tiers.score_by_tiers(len(cookies), _VOLUME_TIERS)
    points += pts
    if issue:
        issues.append(issue)

    # ── Third-party ─────────────────────────────────────────
    pts, issue = _tiers.score_by_tiers(len(third_party), _THIRD_PARTY_TIERS)
    points += pts
    if issue:
        issues.append(issue)

    # ── Known tracking cookies ──────────────────────────────
    pts, issue = _tiers.score_by_tiers(len(tracking), _TRACKING_COOKIE_TIERS)
    points += pts
    if issue:
        issues.append(issue)

    # ── Persistence ─────────────────────────────────────────
    pts, issue = _tiers.score_by_tiers(len(long_lived), _PERSISTENCE_TIERS)
    points += pts
    if issue:
        issues.append(issue)

    log.info(
        "Cookie score",
        data={
            "points": points,
            "max_points": 22,
            "issue_count": len(issues),
        },
    )

    return analysis.CategoryScore(points=points, max_points=22, issues=issues)
