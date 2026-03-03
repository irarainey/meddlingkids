"""Third-party tracker scoring.

Evaluates the number of third-party domains contacted, the
volume of third-party requests, and how many correspond to
known tracking services.
"""

from __future__ import annotations

import re

from src.analysis.scoring import _tiers
from src.data import loader
from src.models import analysis, tracking_data
from src.utils import logger

log = logger.create_logger("Score-ThirdParty")

# ── Tier tables ─────────────────────────────────────────────

_DOMAIN_COUNT_TIERS: tuple[_tiers.Tier, ...] = (
    (50, 14, "{n} third-party domains contacted (extreme)"),
    (35, 12, "{n} third-party domains contacted"),
    (20, 10, "{n} third-party domains contacted"),
    (10, 7, "{n} third-party domains"),
    (5, 5, "{n} third-party domains"),
    (0, 3, None),
)

_REQUEST_VOLUME_TIERS: tuple[_tiers.Tier, ...] = (
    (200, 7, "{n} third-party requests"),
    (100, 5, "{n} third-party requests"),
    (50, 3, None),
    (20, 2, None),
)

_KNOWN_TRACKER_TIERS: tuple[_tiers.Tier, ...] = (
    (15, 10, "{n} known tracking services identified"),
    (8, 8, "{n} known tracking services identified"),
    (4, 6, "{n} known tracking services"),
    (1, 4, "{n} known trackers"),
    (0, 2, None),
)

_CNAME_TIERS: tuple[_tiers.Tier, ...] = (
    (5, 5, "{n} CNAME-cloaked tracker domains detected"),
    (2, 3, "{n} CNAME-cloaked tracker domains detected"),
    (0, 2, "{n} CNAME-cloaked tracker domain detected"),
)


def calculate(
    network_requests: list[tracking_data.NetworkRequest],
    scripts: list[tracking_data.TrackedScript],
    base_domain: str,
    all_urls: list[str],
) -> analysis.CategoryScore:
    """Score third-party tracker presence.

    Assesses the breadth of third-party domain contact, the
    volume of cross-origin requests, and the number of URLs
    matching known tracking service patterns.

    Args:
        network_requests: All captured network requests.
        scripts: All captured scripts.
        base_domain: The analysed site's registrable domain.
        all_urls: Combined list of script + request URLs.

    Returns:
        CategoryScore with uncapped raw points.
    """
    issues: list[str] = []
    points = 0

    log.debug(
        "Third-party scoring input",
        data={
            "network_requests": len(network_requests),
            "scripts": len(scripts),
            "base_domain": base_domain,
            "all_urls": len(all_urls),
        },
    )

    third_party_domains: set[str] = set()
    for req in network_requests:
        if req.is_third_party:
            third_party_domains.add(req.domain)
    for script in scripts:
        if not script.domain.endswith(base_domain):
            third_party_domains.add(script.domain)

    third_party_requests = [r for r in network_requests if r.is_third_party]

    known_trackers: set[str] = set()
    tracking_scripts = loader.get_tracking_scripts()
    for url in all_urls:
        for ts in tracking_scripts:
            if ts.compiled.search(url):
                m = re.search(r"https?://([^/]+)", url)
                if m:
                    known_trackers.add(m.group(1))
                break

    # ── Domain-level tracker lookup ──────────────────────────
    for domain in third_party_domains:
        if loader.is_known_tracker_domain(domain):
            known_trackers.add(domain)

    # ── CNAME cloaking detection ────────────────────────────
    cname_cloaked: set[str] = set()
    for req in network_requests:
        cname_target = loader.get_cname_target(req.domain)
        if cname_target:
            cname_cloaked.add(req.domain)
            known_trackers.add(req.domain)

    log.debug(
        "Third-party detection",
        data={
            "unique_domains": len(third_party_domains),
            "third_party_requests": len(third_party_requests),
            "known_trackers": len(known_trackers),
            "tracker_domains": list(known_trackers)[:10],
            "cname_cloaked": list(cname_cloaked)[:10],
        },
    )

    # ── Domain count ────────────────────────────────────────
    pts, issue = _tiers.score_by_tiers(len(third_party_domains), _DOMAIN_COUNT_TIERS)
    points += pts
    if issue:
        issues.append(issue)

    # ── Request volume ──────────────────────────────────────
    pts, issue = _tiers.score_by_tiers(len(third_party_requests), _REQUEST_VOLUME_TIERS)
    points += pts
    if issue:
        issues.append(issue)

    # ── Known trackers ──────────────────────────────────────
    pts, issue = _tiers.score_by_tiers(len(known_trackers), _KNOWN_TRACKER_TIERS)
    points += pts
    if issue:
        issues.append(issue)

    # ── CNAME cloaking penalty ──────────────────────────────
    pts, issue = _tiers.score_by_tiers(len(cname_cloaked), _CNAME_TIERS)
    points += pts
    if issue:
        issues.append(issue)

    # ── Disconnect category penalties ───────────────────────
    fingerprinting_domains: set[str] = set()
    cryptomining_domains: set[str] = set()
    for domain in third_party_domains | known_trackers:
        category = loader.get_disconnect_category(domain)
        if category is None:
            continue
        cats = category if isinstance(category, list) else [category]
        if "FingerprintingInvasive" in cats:
            fingerprinting_domains.add(domain)
        if "Cryptomining" in cats:
            cryptomining_domains.add(domain)

    if len(fingerprinting_domains) > 0:
        fp_pts = min(len(fingerprinting_domains) * 2, 5)
        points += fp_pts
        issues.append(f"{len(fingerprinting_domains)} invasive fingerprinting service(s) detected")

    if len(cryptomining_domains) > 0:
        points += 5
        issues.append(f"{len(cryptomining_domains)} cryptomining service(s) detected")

    max_points = 48  # 31 base + 5 CNAME + 5 fingerprinting + 5 cryptomining + 2 headroom

    log.info(
        "Third-party score",
        data={
            "points": points,
            "max_points": max_points,
            "issue_count": len(issues),
            "cname_cloaked": len(cname_cloaked),
        },
    )

    return analysis.CategoryScore(
        points=points,
        max_points=max_points,
        issues=issues,
    )
