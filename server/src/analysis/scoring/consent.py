"""Consent, partner, and pre-consent tracking scoring.

Evaluates pre-consent tracking violations, data-sharing
partner counts, partner risk classifications, the quality
of consent disclosures, and the volume of data collection
that occurs before the user has given consent.
"""

from __future__ import annotations

import re

from src.consent import partner_classification
from src.data import loader
from src.models import analysis, consent, tracking_data
from src.utils import logger

log = logger.create_logger("Score-Consent")


def calculate(
    consent_details: consent.ConsentDetails | None,
    cookies: list[tracking_data.TrackedCookie],
    scripts: list[tracking_data.TrackedScript],
    pre_consent_stats: analysis.PreConsentStats | None = None,
) -> analysis.CategoryScore:
    """Score consent-related privacy issues.

    Assesses tracking scripts loaded before consent, the
    number and risk of data-sharing partners, the quality
    of consent language, and the raw volume of data
    collection that occurs before consent is given.

    Args:
        consent_details: Extracted consent dialog info, if any.
        cookies: All captured cookies.
        scripts: All captured scripts.
        pre_consent_stats: Data volumes before consent was
            given.  Used to penalise aggressive pre-consent
            tracking and data collection.

    Returns:
        CategoryScore with uncapped raw points.
    """
    issues: list[str] = []
    points = 0

    log.debug(
        "Consent scoring input",
        data={
            "has_consent": consent_details is not None,
            "cookies": len(cookies),
            "scripts": len(scripts),
        },
    )

    tracking_patterns = loader.get_tracking_scripts()
    tracking_scripts = [s for s in scripts if any(re.search(t.pattern, s.url, re.IGNORECASE) for t in tracking_patterns)]

    log.debug(
        "Pre-consent tracking",
        data={
            "tracking_scripts": len(tracking_scripts),
        },
    )

    # ── Pre-consent tracking ────────────────────────────────
    if len(tracking_scripts) > 10:
        points += 12
        issues.append(f"{len(tracking_scripts)} tracking scripts loaded BEFORE consent given (serious violation)")
    elif len(tracking_scripts) > 5:
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
        points += _score_pre_consent_volume(pre_consent_stats, issues)

        log.info(
            "Consent score",
            data={
                "points": points,
                "max_points": 71,
                "issue_count": len(issues),
            },
        )

        return analysis.CategoryScore(points=points, max_points=71, issues=issues)

    # ── Partner count ───────────────────────────────────────
    extracted_count = len(consent_details.partners)
    claimed_count = consent_details.claimed_partner_count or 0
    partner_count = max(extracted_count, claimed_count)

    log.debug(
        "Consent details",
        data={
            "extracted_partner_count": extracted_count,
            "claimed_partner_count": claimed_count,
            "effective_partner_count": partner_count,
            "purposes": len(consent_details.purposes),
            "categories": len(consent_details.categories),
        },
    )

    if partner_count > 1000:
        points += 20
        issues.append(f"{partner_count} partners share your data (extreme)")
    elif partner_count > 750:
        points += 18
        issues.append(f"{partner_count} partners share your data (extreme)")
    elif partner_count > 500:
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

    # ── Partner risk ────────────────────────────────────────
    if partner_count > 0:
        risk_summary = partner_classification.get_partner_risk_summary(consent_details.partners)
        critical_count = risk_summary.critical_count
        high_count = risk_summary.high_count
        worst_partners = risk_summary.worst_partners

        if critical_count > 0 or high_count > 0:
            log.debug(
                "Partner risk",
                data={
                    "critical": critical_count,
                    "high": high_count,
                    "worst": worst_partners[:5],
                },
            )

        if critical_count > 5:
            points += 8
            issues.append(f"{critical_count} data brokers/identity trackers identified")
        elif critical_count > 2:
            points += 5
            issues.append(f"{critical_count} data brokers among partners")
        elif critical_count > 0:
            points += 3
            issues.append(f"Data broker detected: {worst_partners[0]}")

        if high_count > 10:
            points += 5
            issues.append(f"{high_count} high-risk advertising/tracking partners")
        elif high_count > 5:
            points += 3
        elif high_count > 0:
            points += 2

    # ── Vague consent language ──────────────────────────────
    vague_re = re.compile(
        r"legitimate interest|necessary|essential"
        r"|basic|functional",
        re.I,
    )
    vague_purposes = [p for p in consent_details.purposes if vague_re.search(p)]
    if len(vague_purposes) > 2:
        points += 3
        issues.append("Consent uses vague terms to justify tracking")

    # ── Pre-consent data volume ─────────────────────────────
    # Penalise the raw volume of tracking infrastructure that
    # fires before the user has accepted the consent dialog.
    points += _score_pre_consent_volume(pre_consent_stats, issues)

    log.info(
        "Consent score",
        data={
            "points": points,
            "max_points": 71,
            "issue_count": len(issues),
        },
    )

    return analysis.CategoryScore(points=points, max_points=71, issues=issues)


# ── Pre-consent volume helpers ──────────────────────────────


def _score_pre_consent_volume(
    stats: analysis.PreConsentStats | None,
    issues: list[str],
) -> int:
    """Score *classified* pre-consent tracking activity.

    Only penalises items that matched known tracker patterns
    (tracking cookies, tracking scripts, tracker network
    requests).  Raw infrastructure volume (total scripts,
    total requests) is ignored — modern sites legitimately
    load 30–100+ scripts and make 50–200 requests just to
    render the page.

    Args:
        stats: Categorised pre-consent snapshot.
        issues: Mutable issue list to append to.

    Returns:
        Points to add to the consent category total (max ~15).
    """
    if stats is None:
        return 0

    pts = 0

    # ── Tracking cookies before consent ─────────────────────
    # These are cookies whose names match known tracker
    # patterns (_ga, _fbp, IDE, etc.).  Setting them before
    # consent is a clear GDPR violation.
    if stats.tracking_cookies > 10:
        pts += 5
        issues.append(f"{stats.tracking_cookies} tracking cookies set before consent (serious violation)")
    elif stats.tracking_cookies > 5:
        pts += 3
        issues.append(f"{stats.tracking_cookies} tracking cookies set before consent")
    elif stats.tracking_cookies > 0:
        pts += 1
        issues.append(f"{stats.tracking_cookies} tracking cookie{'s' if stats.tracking_cookies > 1 else ''} set before consent")

    # ── Tracking scripts before consent ─────────────────────
    # Scripts matching known tracker databases (ad scripts,
    # analytics, session replay, etc.).  Non-tracking scripts
    # like UI frameworks are not penalised.
    if stats.tracking_scripts > 10:
        pts += 5
        issues.append(f"{stats.tracking_scripts} tracking scripts loaded before consent")
    elif stats.tracking_scripts > 5:
        pts += 3
        issues.append(f"{stats.tracking_scripts} tracking scripts loaded before consent")
    elif stats.tracking_scripts > 0:
        pts += 1

    # ── Tracker network requests before consent ─────────────
    # Third-party requests to known tracker domains
    # (ad servers, analytics endpoints, pixels, etc.).
    if stats.tracker_requests > 20:
        pts += 5
        issues.append(f"{stats.tracker_requests} tracker requests fired before consent (data sharing without permission)")
    elif stats.tracker_requests > 10:
        pts += 3
        issues.append(f"{stats.tracker_requests} tracker requests fired before consent")
    elif stats.tracker_requests > 3:
        pts += 1

    log.debug(
        "Pre-consent classified",
        data={
            "tracking_cookies": stats.tracking_cookies,
            "tracking_scripts": stats.tracking_scripts,
            "tracker_requests": stats.tracker_requests,
            "total_cookies": stats.total_cookies,
            "total_scripts": stats.total_scripts,
            "total_requests": stats.total_requests,
            "points": pts,
        },
    )

    return pts
