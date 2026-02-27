"""Third-party tracker scoring.

Evaluates the number of third-party domains contacted, the
volume of third-party requests, and how many correspond to
known tracking services.
"""

from __future__ import annotations

import re

from src.data import loader
from src.models import analysis, tracking_data
from src.utils import logger

log = logger.create_logger("Score-ThirdParty")


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
    if len(third_party_domains) > 50:
        points += 14
        issues.append(f"{len(third_party_domains)} third-party domains contacted (extreme)")
    elif len(third_party_domains) > 35:
        points += 12
        issues.append(f"{len(third_party_domains)} third-party domains contacted")
    elif len(third_party_domains) > 20:
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

    # ── Request volume ──────────────────────────────────────
    if len(third_party_requests) > 200:
        points += 7
        issues.append(f"{len(third_party_requests)} third-party requests")
    elif len(third_party_requests) > 100:
        points += 5
        issues.append(f"{len(third_party_requests)} third-party requests")
    elif len(third_party_requests) > 50:
        points += 3
    elif len(third_party_requests) > 20:
        points += 2

    # ── Known trackers ──────────────────────────────────────
    if len(known_trackers) > 15:
        points += 10
        issues.append(f"{len(known_trackers)} known tracking services identified")
    elif len(known_trackers) > 8:
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

    # ── CNAME cloaking penalty ──────────────────────────────
    if len(cname_cloaked) > 5:
        points += 5
        issues.append(f"{len(cname_cloaked)} CNAME-cloaked tracker domains detected")
    elif len(cname_cloaked) > 2:
        points += 3
        issues.append(f"{len(cname_cloaked)} CNAME-cloaked tracker domains detected")
    elif len(cname_cloaked) > 0:
        points += 2
        issues.append(f"{len(cname_cloaked)} CNAME-cloaked tracker domain detected")

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
