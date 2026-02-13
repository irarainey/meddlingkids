"""Privacy score calculator — orchestrator.

Calls each category scoring module, sums the uncapped raw
points, and applies a piecewise linear curve to produce a
0–100 display score with good differentiation across all
severity ranges.
"""

from __future__ import annotations

import re

from src.analysis.scoring import advertising, cookies, data_collection, fingerprinting, sensitive_data, social_media, third_party
from src.analysis.scoring import consent as consent_scoring
from src.models import analysis, consent, tracking_data
from src.utils import logger, url

log = logger.create_logger("PrivacyScore")


# ── Scaling curve ───────────────────────────────────────────

# Two-segment piecewise linear curve.
#
# Below _KNEE the score equals the raw total (no inflation).
# Above _KNEE the slope drops to _UPPER_SLOPE so that heavy
# sites still differentiate — every extra raw point maps to
# a visible score change — without clustering near 100.
#
# The curve reaches 100 at raw = _KNEE + (100 − _KNEE) / _UPPER_SLOPE.
# With _KNEE=40, _UPPER_SLOPE=0.45 that ceiling is raw ≈ 173.
#
#   raw ≈  40 → score  40   (moderate tracking)
#   raw ≈  80 → score  58   (significant tracking)
#   raw ≈ 120 → score  76   (heavy tracking)
#   raw ≈ 140 → score  85   (very heavy tracking)
#   raw ≈ 160 → score  94   (extreme tracking)
#   raw ≈ 173 → score 100   (cap)
_CURVE_KNEE = 40.0
_UPPER_SLOPE = 0.45


def _apply_curve(raw_total: float) -> int:
    """Map an uncapped raw point total to a 0–100 display score.

    Uses a two-segment piecewise linear function:

    - **Below the knee** (raw ≤ 40): ``score = raw`` — no
      inflation, low-tracking sites keep their honest score.
    - **Above the knee** (raw > 40): ``score = 40 + Δ × 0.45``
      — reduced slope preserves variance without exponential
      compression.  Sites 10 raw points apart will always
      show 4–5 display points of difference.

    Args:
        raw_total: Uncapped sum of all category raw points.

    Returns:
        Integer score in the range 0–100.
    """
    if raw_total <= 0:
        return 0
    if raw_total <= _CURVE_KNEE:
        return round(raw_total)
    above = (raw_total - _CURVE_KNEE) * _UPPER_SLOPE
    return min(100, round(_CURVE_KNEE + above))


# ── Public API ──────────────────────────────────────────────


def calculate_privacy_score(
    cookies_list: list[tracking_data.TrackedCookie],
    scripts: list[tracking_data.TrackedScript],
    network_requests: list[tracking_data.NetworkRequest],
    local_storage: list[tracking_data.StorageItem],
    session_storage: list[tracking_data.StorageItem],
    analyzed_url: str,
    consent_details: consent.ConsentDetails | None = None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
) -> analysis.ScoreBreakdown:
    """Calculate the complete privacy score breakdown.

    Each category produces uncapped raw points.  The raw sum
    is then mapped through a non-linear curve to produce a
    0–100 display score that preserves variance at the top end.

    Args:
        cookies_list: All cookies captured during the session.
        scripts: All captured scripts.
        network_requests: All captured network requests.
        local_storage: Captured localStorage items.
        session_storage: Captured sessionStorage items.
        analyzed_url: The URL that was analysed.
        consent_details: Extracted consent dialog info, if any.
        pre_consent_stats: Data volumes before consent was given.

    Returns:
        A :class:`ScoreBreakdown` with per-category detail.
    """
    log.info(
        "Calculating privacy score",
        {
            "cookies": len(cookies_list),
            "scripts": len(scripts),
            "requests": len(network_requests),
        },
    )

    site_hostname = url.extract_domain(analyzed_url)
    base_domain = url.get_base_domain(site_hostname)

    all_urls = [s.url for s in scripts] + [r.url for r in network_requests]

    # ── Per-category scoring (uncapped) ─────────────────────
    cookie_score = cookies.calculate(cookies_list, base_domain)
    third_party_score = third_party.calculate(network_requests, scripts, base_domain, all_urls)
    data_collection_score = data_collection.calculate(local_storage, session_storage, network_requests)
    fingerprint_score = fingerprinting.calculate(cookies_list, scripts, network_requests, all_urls)
    advertising_score = advertising.calculate(scripts, network_requests, cookies_list, all_urls)
    social_media_score = social_media.calculate(scripts, network_requests, all_urls)
    sensitive_data_score = sensitive_data.calculate(consent_details, all_urls)
    consent_score = consent_scoring.calculate(
        consent_details,
        cookies_list,
        scripts,
        pre_consent_stats,
    )

    # ── Apply curve ─────────────────────────────────────────
    raw_total = (
        cookie_score.points
        + third_party_score.points
        + data_collection_score.points
        + fingerprint_score.points
        + advertising_score.points
        + social_media_score.points
        + sensitive_data_score.points
        + consent_score.points
    )
    total_score = _apply_curve(raw_total)

    # ── Top factors ─────────────────────────────────────────
    factors: list[str] = []
    if consent_score.issues:
        factors.extend(consent_score.issues[:2])
    if fingerprint_score.issues:
        factors.extend(fingerprint_score.issues[:2])
    if third_party_score.issues:
        factors.extend(third_party_score.issues[:2])
    if advertising_score.issues:
        factors.extend(advertising_score.issues[:1])
    if cookie_score.issues:
        factors.extend(cookie_score.issues[:1])
    if social_media_score.issues:
        factors.extend(social_media_score.issues[:1])
    if sensitive_data_score.issues:
        factors.extend(sensitive_data_score.issues[:1])

    summary = _generate_summary(site_hostname, total_score, factors)

    log.success(
        "Privacy score calculated",
        {
            "rawTotal": raw_total,
            "curvedScore": total_score,
            "cookies": cookie_score.points,
            "thirdParty": third_party_score.points,
            "dataCollection": data_collection_score.points,
            "fingerprinting": fingerprint_score.points,
            "advertising": advertising_score.points,
            "socialMedia": social_media_score.points,
            "sensitiveData": sensitive_data_score.points,
            "consent": consent_score.points,
        },
    )

    for name, cat in [
        ("cookies", cookie_score),
        ("thirdParty", third_party_score),
        ("dataCollection", data_collection_score),
        ("fingerprinting", fingerprint_score),
        ("advertising", advertising_score),
        ("socialMedia", social_media_score),
        ("sensitiveData", sensitive_data_score),
        ("consent", consent_score),
    ]:
        if cat.issues:
            log.info(
                f"Score detail [{name}]",
                {
                    "points": cat.points,
                    "max": cat.max_points,
                    "issues": cat.issues,
                },
            )

    return analysis.ScoreBreakdown(
        total_score=total_score,
        categories={
            "cookies": cookie_score,
            "thirdPartyTrackers": third_party_score,
            "dataCollection": data_collection_score,
            "fingerprinting": fingerprint_score,
            "advertising": advertising_score,
            "socialMedia": social_media_score,
            "sensitiveData": sensitive_data_score,
            "consent": consent_score,
        },
        factors=factors,
        summary=summary,
    )


# ── Summary generation ──────────────────────────────────────


def _generate_summary(
    site_name: str,
    score: int,
    factors: list[str],
) -> str:
    """Generate a human-readable summary sentence.

    Args:
        site_name: The hostname of the analysed site.
        score: The final 0–100 curved score.
        factors: Top contributing factor descriptions.

    Returns:
        A single-sentence summary of the privacy risk.
    """
    site_name = re.sub(r"^www\.", "", site_name)

    if score >= 80:
        severity = "extensive"
        description = "with aggressive cross-site tracking and data sharing"
    elif score >= 60:
        severity = "significant"
        description = "with multiple advertising networks and third-party trackers"
    elif score >= 40:
        severity = "moderate"
        description = "with standard analytics and some advertising trackers"
    elif score >= 20:
        severity = "limited"
        description = "with basic analytics and minimal third-party presence"
    else:
        severity = "minimal"
        description = "with privacy-respecting practices"

    top_factor = (factors[0] if factors else "").lower()
    if "session replay" in top_factor:
        description = "including session recording that captures your interactions"
    elif "fingerprint" in top_factor:
        description = "including device fingerprinting for cross-site tracking"
    elif "ad network" in top_factor:
        description = f"including {top_factor}"

    return f"{site_name} has {severity} tracking {description}."
