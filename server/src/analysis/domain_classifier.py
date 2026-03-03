"""Deterministic domain classification using local databases.

Classifies third-party domains into tracker categories
(analytics, advertising, social_media, identity_resolution,
other) using the Disconnect tracking-protection list and
partner databases — no LLM call required.

The structured report agent uses this as a first pass so that
known domains are classified instantly and deterministically,
reducing LLM token usage and improving resilience.
"""

from __future__ import annotations

from typing import Literal

from src.data import loader
from src.models import analysis, report
from src.utils import logger
from src.utils import url as url_mod

log = logger.create_logger("DomainClassifier")

# The five tracker categories used by the structured report
# and the client-side network graph.
TrackerCategory = Literal[
    "analytics",
    "advertising",
    "social_media",
    "identity_resolution",
    "other",
]

# ── Disconnect category → TrackerCategory mapping ──────────────

_DISCONNECT_MAP: dict[str, TrackerCategory] = {
    "Advertising": "advertising",
    "Analytics": "analytics",
    "Social": "social_media",
    "FingerprintingGeneral": "identity_resolution",
    "FingerprintingInvasive": "identity_resolution",
    "Cryptomining": "other",
    "Content": "other",
    "Email": "other",
    "EmailAggressive": "other",
    "Anti-fraud": "other",
    "ConsentManagers": "other",
}

# ── Partner category → TrackerCategory mapping ─────────────────

_PARTNER_MAP: dict[str, TrackerCategory] = {
    "advertising": "advertising",
    "analytics": "analytics",
    "social-media": "social_media",
    "identity-resolution": "identity_resolution",
    "data-broker": "identity_resolution",
    "cross-site-tracking": "advertising",
    "content-delivery": "other",
    "fraud-prevention": "other",
    "personalization": "other",
    "measurement": "analytics",
}


# Priority order for Disconnect categories when a domain has
# multiple labels.  Lower index = higher priority.  Purpose-
# oriented labels (Social, Advertising, Analytics) are
# preferred over technique labels (Fingerprinting*).
_DISCONNECT_PRIORITY: list[str] = [
    "Social",
    "Advertising",
    "Analytics",
    "FingerprintingInvasive",
    "FingerprintingGeneral",
]


def _best_disconnect_category(raw_cats: list[str]) -> TrackerCategory:
    """Pick the most specific TrackerCategory from a multi-
    category Disconnect entry.

    Prefers purpose labels (Social, Advertising, Analytics)
    over technique labels (Fingerprinting*).

    Args:
        raw_cats: List of raw Disconnect category strings.

    Returns:
        The best matching ``TrackerCategory``.
    """
    best: TrackerCategory = "other"
    best_rank = len(_DISCONNECT_PRIORITY)
    for raw in raw_cats:
        mapped = _DISCONNECT_MAP.get(raw)
        if mapped is None or mapped == "other":
            continue
        try:
            rank = _DISCONNECT_PRIORITY.index(raw)
        except ValueError:
            rank = len(_DISCONNECT_PRIORITY)
        if rank < best_rank:
            best = mapped
            best_rank = rank
    return best


def classify_domain(domain: str) -> tuple[TrackerCategory, str | None]:
    """Classify a single domain using local databases.

    Checks Disconnect services first (broadest coverage),
    then falls back to partner databases when Disconnect
    has no match or only maps to ``"other"``.

    Disconnect is the primary source because it provides
    domain-level classification (exactly what we need for
    the network graph), while partner databases are
    company-level and can misattribute domains.  For
    example, Facebook appears in the ad-networks partner DB
    (for Facebook Audience Network) but Disconnect correctly
    classifies ``facebook.com`` as Social.

    Args:
        domain: The domain name to classify.

    Returns:
        A ``(category, company)`` tuple.  ``company`` is
        ``None`` when the domain is not found in any database.
        ``category`` defaults to ``"other"`` for unrecognised
        domains.
    """
    category: TrackerCategory = "other"
    company: str | None = None

    # 1. Disconnect services — widest coverage (4000+ domains).
    disc_cat = loader.get_disconnect_category(domain)
    if disc_cat is not None:
        if isinstance(disc_cat, list):
            # Pick the most specific category.  Social,
            # Advertising, and Analytics are more descriptive
            # than Fingerprinting* which is a technique label,
            # not a purpose label.
            category = _best_disconnect_category(disc_cat)
        else:
            category = _DISCONNECT_MAP.get(disc_cat, "other")

        # Grab the company name from the full record.
        services = loader.get_disconnect_services()
        info = services.get(domain)
        if not info:
            base = url_mod.get_base_domain(domain)
            info = services.get(base)
        if info:
            company = info.get("company")

    # If Disconnect gave a specific (non-"other") category,
    # trust it and return immediately.  This prevents partner
    # databases from overriding domain-level classifications
    # with less appropriate company-level ones.
    if category != "other":
        return category, company

    # 2. Partner databases — used only when Disconnect has no
    #    match or mapped to "other".
    base = url_mod.get_base_domain(domain)
    for cfg in loader.PARTNER_CATEGORIES:
        db = loader.get_partner_database(cfg.file)
        for name, entry in db.items():
            entry_domain = (entry.url or "").replace("https://", "").replace("http://", "").rstrip("/").split("/")[0].removeprefix("www.")
            if entry_domain and (entry_domain in (domain, base) or domain.endswith(f".{entry_domain}")):
                mapped = _PARTNER_MAP.get(cfg.category, "other")
                category = mapped
                company = name.title()
                return category, company

    if company:
        return category, company

    return category, None


def build_deterministic_tracking_section(
    tracking_summary: analysis.TrackingSummary,
) -> tuple[report.TrackingTechnologiesSection, list[str]]:
    """Build a tracking technologies section from local data only.

    Classifies every third-party domain in the tracking
    summary using the Disconnect and partner databases.
    Domains that cannot be classified (category="other" with
    no company) are returned separately so the caller can
    optionally send them to an LLM for classification.

    For each classified domain the function also pulls in
    cookie names and storage keys from the domain breakdown
    data so the entries are as complete as possible.

    Args:
        tracking_summary: Pre-built tracking summary with
            domain breakdown and third-party domain list.

    Returns:
        A ``(section, unclassified_domains)`` tuple.
        ``section`` contains deterministically classified
        trackers.  ``unclassified_domains`` lists domains
        that could not be matched to any local database.
    """
    # Build a domain → breakdown lookup for cookie/script data.
    breakdown_map: dict[str, analysis.DomainBreakdown] = {db.domain: db for db in tracking_summary.domain_breakdown}

    # Accumulate TrackerEntry objects by category.
    buckets: dict[TrackerCategory, dict[str, report.TrackerEntry]] = {
        "analytics": {},
        "advertising": {},
        "social_media": {},
        "identity_resolution": {},
        "other": {},
    }
    unclassified: list[str] = []

    for domain in tracking_summary.third_party_domains:
        category, company = classify_domain(domain)

        if category == "other" and company is None:
            unclassified.append(domain)
            continue

        # Use the company name as the grouping key so
        # multiple subdomains roll up under one tracker.
        label = company or domain
        entry_key = label.lower()

        bd = breakdown_map.get(domain)
        cookies = bd.cookie_names if bd else []

        if entry_key in buckets[category]:
            # Merge domains/cookies into existing entry.
            existing = buckets[category][entry_key]
            if domain not in existing.domains:
                existing.domains.append(domain)
            for c in cookies:
                if c not in existing.cookies:
                    existing.cookies.append(c)
        else:
            purpose = _infer_purpose(category)
            buckets[category][entry_key] = report.TrackerEntry(
                name=label,
                domains=[domain],
                cookies=cookies,
                purpose=purpose,
            )

    section = report.TrackingTechnologiesSection(
        analytics=list(buckets["analytics"].values()),
        advertising=list(buckets["advertising"].values()),
        identity_resolution=list(buckets["identity_resolution"].values()),
        social_media=list(buckets["social_media"].values()),
        other=list(buckets["other"].values()),
    )

    total = (
        len(section.analytics)
        + len(section.advertising)
        + len(section.identity_resolution)
        + len(section.social_media)
        + len(section.other)
    )
    log.info(
        "Deterministic domain classification complete",
        {
            "classified": total,
            "unclassified": len(unclassified),
            "analytics": len(section.analytics),
            "advertising": len(section.advertising),
            "identity": len(section.identity_resolution),
            "social": len(section.social_media),
            "other": len(section.other),
        },
    )

    return section, unclassified


def merge_tracking_sections(
    deterministic: report.TrackingTechnologiesSection,
    llm_section: report.TrackingTechnologiesSection | None,
) -> report.TrackingTechnologiesSection:
    """Merge deterministic and LLM-generated tracking sections.

    The deterministic section is the base.  LLM entries are
    added only when they introduce a domain not already
    present in the deterministic section.  This ensures
    local-database classifications take priority while the
    LLM can fill in gaps for unknown domains.

    Args:
        deterministic: Section from local databases.
        llm_section: Optional section from the LLM (may be
            ``None`` if the LLM call failed or was skipped).

    Returns:
        Merged section with deterministic data as the
        authoritative base.
    """
    if llm_section is None:
        return deterministic

    # Collect all domains already classified deterministically.
    known_domains: set[str] = set()
    for entries in (
        deterministic.analytics,
        deterministic.advertising,
        deterministic.identity_resolution,
        deterministic.social_media,
        deterministic.other,
    ):
        for entry in entries:
            known_domains.update(entry.domains)

    # Walk the LLM section and add entries whose domains
    # are not yet covered.
    category_pairs: list[tuple[list[report.TrackerEntry], list[report.TrackerEntry]]] = [
        (llm_section.analytics, deterministic.analytics),
        (llm_section.advertising, deterministic.advertising),
        (llm_section.identity_resolution, deterministic.identity_resolution),
        (llm_section.social_media, deterministic.social_media),
        (llm_section.other, deterministic.other),
    ]

    for llm_entries, det_entries in category_pairs:
        for llm_entry in llm_entries:
            new_domains = [d for d in llm_entry.domains if d not in known_domains]
            if new_domains:
                det_entries.append(
                    report.TrackerEntry(
                        name=llm_entry.name,
                        domains=new_domains,
                        cookies=llm_entry.cookies,
                        storage_keys=llm_entry.storage_keys,
                        purpose=llm_entry.purpose,
                        url=llm_entry.url,
                    )
                )
                known_domains.update(new_domains)

    return deterministic


def _infer_purpose(category: TrackerCategory) -> str:
    """Return a short default purpose string for a category.

    Used when domain classification is deterministic and no
    richer description is available from the database.

    Args:
        category: Tracker category.

    Returns:
        Human-readable purpose string.
    """
    return {
        "analytics": "Analytics and measurement",
        "advertising": "Advertising and ad targeting",
        "social_media": "Social media tracking",
        "identity_resolution": "Identity resolution and cross-site tracking",
        "other": "Third-party service",
    }[category]
