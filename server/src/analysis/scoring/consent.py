"""Consent, partner, and page-load tracking scoring.

Evaluates the volume of tracking infrastructure on the page,
data-sharing partner counts, partner risk classifications,
the quality of consent disclosures, and the amount of
tracking-related activity present on initial page load
before any dialogs were dismissed.
"""

from __future__ import annotations

import re

from src.analysis.scoring import _tiers
from src.consent import partner_classification
from src.data import loader
from src.models import analysis, consent, tracking_data
from src.utils import logger

log = logger.create_logger("Score-Consent")

# Pre-compiled pattern for vague consent language detection
_VAGUE_CONSENT_RE = re.compile(
    r"legitimate interest|necessary|essential"
    r"|basic|functional",
    re.I,
)

# ── Tier tables ─────────────────────────────────────────────

_TRACKING_SCRIPT_TIERS: tuple[_tiers.Tier, ...] = (
    (10, 12, "{n} tracking scripts detected on page"),
    (5, 10, "{n} tracking scripts detected on page"),
    (2, 7, "{n} tracking scripts detected on page"),
    (0, 4, "Tracking scripts detected on page"),
)

_PARTNER_COUNT_TIERS: tuple[_tiers.Tier, ...] = (
    (1000, 20, "{n} partners share your data (extreme)"),
    (750, 18, "{n} partners share your data (extreme)"),
    (500, 15, "{n} partners share your data (extreme)"),
    (300, 12, "{n} partners share your data (massive)"),
    (150, 10, "{n} partners share your data (excessive)"),
    (75, 8, "{n} partners share your data"),
    (30, 6, "{n} data sharing partners"),
    (10, 4, "{n} data sharing partners"),
    (0, 2, None),
)

_HIGH_RISK_PARTNER_TIERS: tuple[_tiers.Tier, ...] = (
    (10, 5, "{n} high-risk advertising/tracking partners"),
    (5, 3, None),
    (0, 2, None),
)

_PRE_CONSENT_COOKIE_TIERS: tuple[_tiers.Tier, ...] = (
    (10, 5, "{n} tracking cookies present on initial page load"),
    (5, 3, "{n} tracking cookies present on initial page load"),
    (0, 1, "{n} tracking cookies present on initial page load"),
)

_PRE_CONSENT_SCRIPT_TIERS: tuple[_tiers.Tier, ...] = (
    (10, 5, "{n} tracking scripts loaded on initial page load"),
    (5, 3, "{n} tracking scripts loaded on initial page load"),
    (0, 1, None),
)

_PRE_CONSENT_REQUEST_TIERS: tuple[_tiers.Tier, ...] = (
    (20, 5, "{n} tracker requests observed on initial page load"),
    (10, 3, "{n} tracker requests observed on initial page load"),
    (3, 1, None),
)


def calculate(
    consent_details: consent.ConsentDetails | None,
    cookies: list[tracking_data.TrackedCookie],
    scripts: list[tracking_data.TrackedScript],
    pre_consent_stats: analysis.PreConsentStats | None = None,
) -> analysis.CategoryScore:
    """Score consent-related privacy issues.

    Assesses the volume of tracking scripts on the page,
    the number and risk of data-sharing partners, the quality
    of consent language, and the amount of tracking-related
    activity present on initial page load before any dialogs
    were dismissed.

    Args:
        consent_details: Extracted consent dialog info, if any.
        cookies: All captured cookies.
        scripts: All captured scripts.
        pre_consent_stats: Classified tracking volumes captured
            on initial page load before any dialogs were
            dismissed.

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
    tracking_scripts = [s for s in scripts if any(t.compiled.search(s.url) for t in tracking_patterns)]

    log.debug(
        "Tracking script detection",
        data={
            "tracking_scripts": len(tracking_scripts),
        },
    )

    # ── Tracking script volume ───────────────────────────────
    # Penalise the total number of known tracking scripts
    # present on the page.  Whether they loaded before or
    # after consent is scored separately via pre_consent_stats.
    pts, issue = _tiers.score_by_tiers(len(tracking_scripts), _TRACKING_SCRIPT_TIERS)
    points += pts
    if issue:
        issues.append(issue)

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

    pts, issue = _tiers.score_by_tiers(partner_count, _PARTNER_COUNT_TIERS)
    points += pts
    if issue:
        issues.append(issue)

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

        pts, issue = _tiers.score_by_tiers(high_count, _HIGH_RISK_PARTNER_TIERS)
        points += pts
        if issue:
            issues.append(issue)

    # ── Vague consent language ──────────────────────────────
    vague_purposes = [p for p in consent_details.purposes if _VAGUE_CONSENT_RE.search(p)]
    if len(vague_purposes) > 2:
        points += 3
        issues.append("Consent uses vague terms to justify tracking")

    # ── Page-load tracking volume ───────────────────────────
    # Penalise known tracking activity present on initial
    # page load before any dialog was dismissed.
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
    """Score tracking activity present on initial page load.

    Only penalises items that matched known tracker patterns
    (tracking cookies, tracking scripts, tracker network
    requests).  Raw infrastructure volume (total scripts,
    total requests) is ignored — modern sites legitimately
    load 30–100+ scripts and make 50–200 requests just to
    render the page.

    The snapshot is taken before any overlay or dialog is
    dismissed.  We cannot determine whether observed scripts
    actually use the cookies present, whether the dialog is
    a consent dialog (vs sign-in), or whether the tracked
    activity is something the user could consent to.  Issue
    language is therefore purely observational.

    Args:
        stats: Categorised page-load snapshot.
        issues: Mutable issue list to append to.

    Returns:
        Points to add to the consent category total (max ~15).
    """
    if stats is None:
        return 0

    pts = 0

    # ── Tracking cookies on page load ───────────────────────
    # Cookies whose names match known tracker patterns
    # (_ga, _fbp, IDE, etc.) present on initial page load
    # before any dialog was dismissed.
    tier_pts, tier_issue = _tiers.score_by_tiers(stats.tracking_cookies, _PRE_CONSENT_COOKIE_TIERS)
    pts += tier_pts
    if tier_issue:
        issues.append(tier_issue)

    # ── Tracking scripts on page load ───────────────────────
    # Scripts matching known tracker databases (ad scripts,
    # analytics, session replay, etc.).  Non-tracking scripts
    # like UI frameworks are not penalised.
    tier_pts, tier_issue = _tiers.score_by_tiers(stats.tracking_scripts, _PRE_CONSENT_SCRIPT_TIERS)
    pts += tier_pts
    if tier_issue:
        issues.append(tier_issue)

    # ── Tracker network requests on page load ───────────────
    # Third-party requests to known tracker domains
    # (ad servers, analytics endpoints, pixels, etc.).
    tier_pts, tier_issue = _tiers.score_by_tiers(stats.tracker_requests, _PRE_CONSENT_REQUEST_TIERS)
    pts += tier_pts
    if tier_issue:
        issues.append(tier_issue)

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
