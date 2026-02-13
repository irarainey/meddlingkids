"""Cookie-based privacy scoring.

Evaluates cookie volume, third-party cookies, known tracking
cookie patterns, and long-lived persistence to produce a
category score.
"""

from __future__ import annotations

import time

from src.analysis import tracker_patterns
from src.models import analysis, tracking_data
from src.utils import logger

log = logger.create_logger("Score-Cookies")


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
    if len(cookies) > 100:
        points += 8
        issues.append(f"{len(cookies)} cookies set (extreme)")
    elif len(cookies) > 50:
        points += 6
        issues.append(f"{len(cookies)} cookies set (heavy)")
    elif len(cookies) > 30:
        points += 5
        issues.append(f"{len(cookies)} cookies set (heavy tracking)")
    elif len(cookies) > 15:
        points += 4
        issues.append(f"{len(cookies)} cookies set")
    elif len(cookies) > 5:
        points += 2

    # ── Third-party ─────────────────────────────────────────
    if len(third_party) > 15:
        points += 7
        issues.append(f"{len(third_party)} third-party cookies")
    elif len(third_party) > 5:
        points += 5
        issues.append(f"{len(third_party)} third-party cookies")
    elif len(third_party) > 2:
        points += 3
        issues.append(f"{len(third_party)} third-party cookies")
    elif len(third_party) > 0:
        points += 2

    # ── Known tracking cookies ──────────────────────────────
    if len(tracking) > 3:
        points += 5
        issues.append(f"{len(tracking)} known tracking cookies")
    elif len(tracking) > 0:
        points += 3
        issues.append(f"{len(tracking)} tracking cookies detected")

    # ── Persistence ─────────────────────────────────────────
    if len(long_lived) > 3:
        points += 2
        issues.append(f"{len(long_lived)} cookies persist over 1 year")
    elif len(long_lived) > 0:
        points += 1

    log.info(
        "Cookie score",
        data={
            "points": points,
            "max_points": 22,
            "issue_count": len(issues),
        },
    )

    return analysis.CategoryScore(points=points, max_points=22, issues=issues)
