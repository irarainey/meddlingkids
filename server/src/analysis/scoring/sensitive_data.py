"""Sensitive data and content profiling scoring.

Evaluates whether the site collects sensitive personal data
(location/ISP, health, political, financial, etc.), uses
content-topic profiling services, or tracks users by the
type of content they consume.
"""

from __future__ import annotations

import re

from src.analysis import tracker_patterns
from src.models import analysis, consent
from src.utils import logger

log = logger.create_logger("Score-SensitiveData")


# ── Human-readable labels for sensitive purpose matches ─────
# Maps a keyword found in the regex pattern source to an
# issue description.  Checked in order; the first match wins
# per pattern.

_PURPOSE_LABELS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"location|geo|gps|postcode|zip", re.I),
        "Location / postcode data collection disclosed",
    ),
    (re.compile(r"politic", re.I), "Political interest tracking disclosed"),
    (
        re.compile(r"health|medical|pharma|wellness", re.I),
        "Health-related data collection disclosed",
    ),
    (
        re.compile(r"financial|credit|income|debt|mortgage", re.I),
        "Financial data tracking disclosed",
    ),
    (re.compile(r"pregnan|fertility|baby", re.I), "Pregnancy / fertility tracking disclosed"),
    (
        re.compile(r"mental.?health|depression|anxiety", re.I),
        "Mental health data tracking disclosed",
    ),
    (
        re.compile(r"addiction|gambling|alcohol|substance", re.I),
        "Addiction / substance-related tracking disclosed",
    ),
    (re.compile(r"child|minor|kid", re.I), "Child-related data tracking disclosed"),
    (re.compile(r"criminal|arrest|conviction", re.I), "Criminal record data tracking disclosed"),
    (re.compile(r"disabilit|handicap", re.I), "Disability-related data tracking disclosed"),
    (re.compile(r"religio", re.I), "Religious data tracking disclosed"),
    (re.compile(r"ethnic|racial", re.I), "Ethnic / racial data tracking disclosed"),
    (re.compile(r"sexual|sex", re.I), "Sexual orientation data tracking disclosed"),
    (re.compile(r"immigration|visa|asylum", re.I), "Immigration-related data tracking disclosed"),
    (re.compile(r"trade.?union|union.?member", re.I), "Trade union membership tracking disclosed"),
    (re.compile(r"legal.?aid|solicitor|lawyer", re.I), "Legal services data tracking disclosed"),
]


def _resolve_purpose_label(pattern_source: str) -> str:
    """Map a regex pattern source to a human-readable label."""
    for matcher, label in _PURPOSE_LABELS:
        if matcher.search(pattern_source):
            return label
    return "Sensitive personal data collection disclosed"


def calculate(
    consent_details: consent.ConsentDetails | None,
    all_urls: list[str],
) -> analysis.CategoryScore:
    """Score sensitive data and content profiling indicators.

    Checks:
    - Consent-dialog disclosures for sensitive data categories
      (health, politics, finance, location, etc.)
    - URL patterns for granular location / ISP / postcode
      tracking services
    - Identity resolution services (cross-site linking)
    - Content topic profiling / audience segmentation services

    Args:
        consent_details: Extracted consent dialog info, if any.
        all_urls: Combined script + request URLs.

    Returns:
        CategoryScore with uncapped raw points.
    """
    issues: list[str] = []
    points = 0

    log.debug(
        "Sensitive data scoring input",
        data={
            "has_consent": consent_details is not None,
            "all_urls": len(all_urls),
        },
    )

    # ── Sensitive purpose disclosures (consent text) ────────
    # Scan ALL matching categories, not just the first.
    if consent_details:
        all_purposes = " ".join(
            [
                *consent_details.purposes,
                *[c.description for c in consent_details.categories],
                consent_details.raw_text or "",
            ]
        )
        matched_purposes = 0
        for p in tracker_patterns.SENSITIVE_PURPOSES:
            if p.search(all_purposes):
                label = _resolve_purpose_label(p.pattern)
                if label not in issues:
                    matched_purposes += 1
                    issues.append(label)

        if matched_purposes > 3:
            points += 6
        elif matched_purposes > 1:
            points += 4
        elif matched_purposes > 0:
            points += 2

        log.debug(
            "Sensitive purposes matched",
            data={
                "matched_purposes": matched_purposes,
                "labels": [i for i in issues],
            },
        )

    # ── Granular location / ISP tracking ────────────────────
    location_hits: set[str] = set()
    for url in all_urls:
        for p in tracker_patterns.LOCATION_ISP_PATTERNS:
            if p.search(url):
                src = p.pattern
                if re.search(r"post.?code|zip.?code", src, re.I):
                    location_hits.add("postcode")
                elif re.search(r"isp|whois|network", src, re.I):
                    location_hits.add("isp")
                elif re.search(r"geolocation|getCurrentPosition|precise|exact", src, re.I):
                    location_hits.add("precise")
                elif re.search(r"geo.?target|geo.?fence|geo.?zone|geo.?edge", src, re.I):
                    location_hits.add("geofence")
                else:
                    location_hits.add("ip-geo")
                break

    if location_hits:
        log.debug(
            "Location/ISP tracking detected",
            data={
                "tiers": list(location_hits),
            },
        )

    if "precise" in location_hits or "postcode" in location_hits:
        points += 6
        extras = []
        if "postcode" in location_hits:
            extras.append("postcode-level")
        if "precise" in location_hits:
            extras.append("precise GPS")
        if "isp" in location_hits:
            extras.append("broadband provider")
        issues.append(f"Granular location tracking detected ({', '.join(extras)})")
    elif "geofence" in location_hits:
        points += 5
        issues.append("Geo-fencing / geo-targeted tracking detected")
    elif "isp" in location_hits:
        points += 4
        issues.append("ISP / broadband provider tracking detected")
    elif "ip-geo" in location_hits:
        points += 3
        issues.append("IP-based geolocation tracking detected")

    # ── Identity resolution ─────────────────────────────────
    if any(
        re.search(
            r"liveramp|unified.?id|id5|lotame"
            r"|thetradedesk.*unified",
            url,
            re.I,
        )
        for url in all_urls
    ):
        points += 4
        issues.append("Cross-site identity tracking (identity resolution service)")

    # ── Content topic profiling ─────────────────────────────
    profiling_services: set[str] = set()
    for url in all_urls:
        for p in tracker_patterns.CONTENT_PROFILING_PATTERNS:
            if p.search(url):
                m = re.search(r"https?://([^/]+)", url)
                if m:
                    profiling_services.add(m.group(1))
                break

    if len(profiling_services) > 0:
        log.debug(
            "Content profiling services",
            data={
                "services": list(profiling_services),
            },
        )

    if len(profiling_services) > 2:
        points += 6
        issues.append(f"{len(profiling_services)} content profiling services track which topics you read")
    elif len(profiling_services) > 0:
        points += 4
        issues.append("Content topic profiling active - what you read is categorised and shared")

    log.info(
        "Sensitive data score",
        data={
            "points": points,
            "max_points": 22,
            "issue_count": len(issues),
        },
    )

    return analysis.CategoryScore(points=points, max_points=22, issues=issues)
