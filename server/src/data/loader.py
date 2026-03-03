"""
Data loader for tracker, partner, and GDPR/TCF reference databases.
Loads JSON files and compiles patterns into regex objects.

The JSON data files live alongside this module in partners/, trackers/,
and consent/ subdirectories.
"""

from __future__ import annotations

import functools
import json
import pathlib
import re
from typing import Any

from src.models import partners
from src.utils import logger
from src.utils import url as url_mod

log = logger.create_logger("DataLoader")

# Resolve path to the data directory (same directory as this module)
_DATA_DIR = pathlib.Path(__file__).resolve().parent

# ============================================================================
# JSON File Loading
# ============================================================================


def _load_json(relative_path: str) -> Any:
    """Load and parse a JSON file relative to the data directory.

    Raises:
        FileNotFoundError: If the JSON file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
        ValueError: If the path escapes the data directory.
    """
    full_path = (_DATA_DIR / relative_path).resolve()
    if not full_path.is_relative_to(_DATA_DIR):
        raise ValueError(f"Path escapes data directory: {relative_path}")
    if not full_path.exists():
        raise FileNotFoundError(f"Data file not found: {relative_path}")
    with open(full_path, encoding="utf-8") as f:
        try:
            data = json.load(f)
            log.debug("Loaded data file", {"file": relative_path})
            return data
        except json.JSONDecodeError as exc:
            log.error(
                "Invalid JSON in data file",
                {"file": relative_path, "error": exc.msg},
            )
            raise json.JSONDecodeError(
                f"Invalid JSON in {relative_path}: {exc.msg}",
                exc.doc,
                exc.pos,
            ) from exc


# ============================================================================
# Script Pattern Loading
# ============================================================================


def _load_script_patterns(filename: str) -> list[partners.ScriptPattern]:
    """Load script patterns from a JSON file.

    Compiles each regex once at load time so that
    matching is fast on every subsequent call.
    """
    raw: list[dict[str, str]] = _load_json(f"trackers/{filename}")
    patterns = [
        partners.ScriptPattern(
            pattern=entry["pattern"],
            description=entry["description"],
            compiled=re.compile(entry["pattern"], re.IGNORECASE),
        )
        for entry in raw
    ]
    log.info("Script patterns compiled", {"file": filename, "count": len(patterns)})
    return patterns


@functools.cache
def get_tracking_scripts() -> list[partners.ScriptPattern]:
    """Get tracking scripts database (loaded once and cached)."""
    return _load_script_patterns("tracking-scripts.json")


@functools.cache
def get_benign_scripts() -> list[partners.ScriptPattern]:
    """Get benign scripts database (loaded once and cached)."""
    return _load_script_patterns("benign-scripts.json")


@functools.cache
def get_tracking_cookies() -> dict[str, Any]:
    """Get known tracking cookie definitions (loaded once and cached).

    Returns the full JSON structure containing cookie entries,
    risk levels, and privacy notes.
    """
    result: dict[str, Any] = _load_json("trackers/tracking-cookies.json")
    return result


def get_tracking_cookie_patterns() -> list[tuple[re.Pattern[str], str, str, str]]:
    """Build compiled regex patterns from the tracking cookies data.

    Returns a list of tuples: ``(pattern, description, set_by, purpose)``.
    The result is not cached because ``get_tracking_cookies`` is already
    cached, and compiling twenty patterns is cheap.
    """
    data = get_tracking_cookies()
    entries: dict[str, dict[str, str]] = data.get("cookies", {})
    return [
        (
            re.compile(entry["pattern"], re.I),
            entry["description"],
            entry["setBy"],
            entry["purpose"],
        )
        for key, entry in entries.items()
        if isinstance(entry, dict)
    ]


def get_tracking_cookie_risk_map() -> dict[str, str]:
    """Return purpose → risk-level mapping from the tracking cookies data."""
    data = get_tracking_cookies()
    result: dict[str, str] = data.get("risk_levels", {})
    return result


def get_tracking_cookie_privacy_map() -> dict[str, str]:
    """Return purpose → privacy-note mapping from the tracking cookies data."""
    data = get_tracking_cookies()
    result: dict[str, str] = data.get("privacy_notes", {})
    return result


def get_tracking_cookie_vendor_index() -> dict[str, dict[str, Any]]:
    """Return setBy → vendor metadata from the tracking cookies data.

    Each entry may contain ``category``, ``gvl_ids``, ``atp_ids``,
    ``url``, and ``concerns``.
    """
    data = get_tracking_cookies()
    result: dict[str, dict[str, Any]] = data.get("vendors", {})
    return result


def build_tracking_cookie_context() -> str:
    """Build an LLM-friendly reference section from the known tracking cookies database.

    Groups cookies by ``setBy`` (platform) and lists each cookie's
    name, purpose, and description so the LLM can classify observed
    cookies accurately without relying solely on training data.

    Returns:
        Formatted reference section string, or empty string if
        the database is empty.
    """
    data = get_tracking_cookies()
    entries: dict[str, Any] = data.get("cookies", {})

    # Group cookie entries by platform (setBy).
    grouped: dict[str, list[dict[str, str]]] = {}
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        platform = entry.get("setBy", "Unknown")
        grouped.setdefault(platform, []).append(
            {
                "name": key,
                "pattern": entry.get("pattern", ""),
                "purpose": entry.get("purpose", ""),
                "description": entry.get("description", ""),
            }
        )

    if not grouped:
        return ""

    lines = [
        "",
        "## Known Tracking Cookie Reference",
        "",
    ]

    for platform, cookies in sorted(grouped.items()):
        lines.append(f"### {platform}")
        for cookie in cookies:
            desc = f" — {cookie['description']}" if cookie["description"] else ""
            lines.append(f"- {cookie['name']} ({cookie['purpose']}){desc}")
        lines.append("")

    # Include risk-level mapping.
    risk_map = data.get("risk_levels", {})
    if risk_map:
        lines.append("### Cookie Purpose Risk Levels")
        for purpose, level in risk_map.items():
            lines.append(f"- {purpose}: {level}")
        lines.append("")

    return "\n".join(lines)


# ============================================================================
# Tracking Storage Key Loading
# ============================================================================


@functools.cache
def get_tracking_storage_keys() -> dict[str, Any]:
    """Get known tracking storage key definitions (loaded once and cached).

    Returns the full JSON structure containing storage key entries,
    risk levels, and privacy notes.
    """
    result: dict[str, Any] = _load_json("trackers/tracking-storage.json")
    return result


def get_tracking_storage_patterns() -> list[tuple[re.Pattern[str], str, str, str]]:
    """Build compiled regex patterns from the tracking storage keys data.

    Returns a list of tuples: ``(pattern, description, set_by, purpose)``.
    """
    data = get_tracking_storage_keys()
    entries: dict[str, dict[str, str]] = data.get("keys", {})
    return [
        (
            re.compile(entry["pattern"], re.I),
            entry["description"],
            entry["setBy"],
            entry["purpose"],
        )
        for key, entry in entries.items()
        if isinstance(entry, dict)
    ]


def get_tracking_storage_risk_map() -> dict[str, str]:
    """Return purpose → risk-level mapping from the tracking storage data."""
    data = get_tracking_storage_keys()
    result: dict[str, str] = data.get("risk_levels", {})
    return result


def get_tracking_storage_privacy_map() -> dict[str, str]:
    """Return purpose → privacy-note mapping from the tracking storage data."""
    data = get_tracking_storage_keys()
    result: dict[str, str] = data.get("privacy_notes", {})
    return result


def get_tracking_storage_vendor_index() -> dict[str, dict[str, Any]]:
    """Return setBy → vendor metadata from the tracking storage data.

    Each entry may contain ``category``, ``gvl_ids``, ``atp_ids``,
    ``url``, and ``concerns``.
    """
    data = get_tracking_storage_keys()
    result: dict[str, dict[str, Any]] = data.get("vendors", {})
    return result


# ============================================================================
# Tracker Domain Loading
# ============================================================================


@functools.cache
def get_tracker_domains() -> dict[str, str]:
    """Get known tracker domain classifications.

    Returns a dictionary mapping domain names to their
    classification (``"block"`` or ``"cookieblock"``).
    """
    data: dict[str, Any] = _load_json("trackers/tracker-domains.json")
    result: dict[str, str] = data.get("domains", {})
    log.info("Tracker domains loaded", {"count": len(result)})
    return result


def is_known_tracker_domain(domain: str) -> bool:
    """Check if a domain is a known tracker.

    Checks the exact domain first, then falls back to the
    registrable base domain for subdomain matching.

    Args:
        domain: A domain name to look up.

    Returns:
        True if the domain is classified as a tracker.
    """
    tracker_domains = get_tracker_domains()
    if domain in tracker_domains:
        return True
    # Try base domain for subdomain matching
    from src.utils import url as url_mod

    base = url_mod.get_base_domain(domain)
    return base in tracker_domains


# ============================================================================
# CNAME Cloaking Domain Loading
# ============================================================================


@functools.cache
def get_cname_domains() -> dict[str, str]:
    """Get CNAME-cloaked domain mappings.

    Returns a dictionary mapping first-party subdomains to
    their actual tracker CNAME destinations.  Used to detect
    CNAME cloaking where trackers disguise themselves as
    first-party domains.

    """
    data: dict[str, Any] = _load_json(
        "trackers/cname-domains.json",
    )
    # Remove the _description metadata key
    result = {k: v for k, v in data.items() if not k.startswith("_")}
    log.info("CNAME domains loaded", {"count": len(result)})
    return result


def get_cname_target(domain: str) -> str | None:
    """Look up the CNAME target for a potentially cloaked domain.

    Args:
        domain: A domain/subdomain to check for cloaking.

    Returns:
        The real tracker domain, or ``None`` if not cloaked.
    """
    return get_cname_domains().get(domain)


# ============================================================================
# Disconnect Tracking Protection
# ============================================================================


@functools.cache
def get_disconnect_services() -> dict[str, dict[str, Any]]:
    """Get Disconnect tracker domain categories.

    Returns a dictionary mapping domain names to their
    tracking category and operating company.  Categories
    include Advertising, Analytics, FingerprintingInvasive,
    Social, Cryptomining, and others.

    """
    data: dict[str, Any] = _load_json(
        "trackers/disconnect-services.json",
    )
    result: dict[str, dict[str, Any]] = data.get("domains", {})
    log.info("Disconnect services loaded", {"count": len(result)})
    return result


def get_disconnect_category(domain: str) -> str | list[str] | None:
    """Get the Disconnect tracking category for a domain.

    Args:
        domain: A domain name to look up.

    Returns:
        A category string, list of categories, or ``None``.
    """
    services = get_disconnect_services()
    info = services.get(domain)
    if info:
        return info.get("category")
    # Try base domain
    from src.utils import url as url_mod

    base = url_mod.get_base_domain(domain)
    info = services.get(base)
    if info:
        return info.get("category")
    return None


def build_disconnect_context(third_party_domains: list[str]) -> str:
    """Build an LLM-friendly reference section from the Disconnect tracking
    protection list for the observed third-party domains.

    Looks up each domain in the Disconnect services database and
    groups matches by category, showing the operating company for
    each domain.

    Args:
        third_party_domains: Domains observed as third-party requests.

    Returns:
        Formatted reference section string, or empty string if
        no domains match.
    """
    services = get_disconnect_services()
    if not services or not third_party_domains:
        return ""

    from src.utils import url as url_mod

    # Look up each domain, dedup by (domain, category, company).
    matches: dict[str, list[tuple[str, str]]] = {}
    seen: set[str] = set()
    for domain in third_party_domains:
        if domain in seen:
            continue
        seen.add(domain)
        info = services.get(domain)
        if not info:
            base = url_mod.get_base_domain(domain)
            info = services.get(base)
        if not info:
            continue
        company = info.get("company", "Unknown")
        category = info.get("category", "Other")
        # category may be a string or list
        cats = category if isinstance(category, list) else [category]
        for cat in cats:
            matches.setdefault(cat, []).append((domain, company))

    if not matches:
        return ""

    lines = [
        "",
        "## Known Tracker Domain Classifications (Disconnect)",
        "",
    ]

    for cat in sorted(matches):
        lines.append(f"### {cat}")
        # Deduplicate and sort entries within each category.
        unique = sorted(set(matches[cat]))
        for domain, company in unique:
            lines.append(f"- {domain} → {company}")
        lines.append("")

    return "\n".join(lines)


def _humanise_disconnect_category(raw: str) -> str:
    """Convert a Disconnect category slug into a readable label.

    Examples: ``FingerprintingGeneral`` → ``Fingerprinting``,
    ``Advertising`` → ``Advertising``.
    """
    mapping: dict[str, str] = {
        "FingerprintingGeneral": "Fingerprinting",
        "FingerprintingInvasive": "Invasive Fingerprinting",
        "Cryptomining": "Cryptomining",
        "Social": "Social Media",
        "ConsentManagers": "Consent Management",
        "EmailAggressive": "Email Tracking",
        "Anti-fraud": "Anti-Fraud",
    }
    return mapping.get(raw, raw)


# Categories that are too generic to be useful as the sole label.
_GENERIC_CATEGORIES = {"Email", "Content"}


def get_domain_description(domain: str) -> dict[str, str | None]:
    """Build a short description for a domain from known databases.

    Checks Disconnect services (category + company), the partner
    databases, and the tracker-domains list.  Returns a dict with
    ``company``, ``description``, and ``url`` keys (any may be
    ``None``).
    """
    from src.utils import url as url_mod

    # Normalise: cookie domains often have a leading dot (e.g. ".google.com").
    domain = domain.lstrip(".")

    company: str | None = None
    description: str | None = None

    # 1. Disconnect services — richest metadata (category + company).
    services = get_disconnect_services()
    info = services.get(domain)
    if not info:
        base = url_mod.get_base_domain(domain)
        info = services.get(base)
    if info:
        company = info.get("company")
        raw_cats: str | list[str] = info.get("category", "Tracking")
        cats = raw_cats if isinstance(raw_cats, list) else [raw_cats]
        labels = [_humanise_disconnect_category(c) for c in cats if c not in _GENERIC_CATEGORIES]
        if not labels:
            labels = [_humanise_disconnect_category(c) for c in cats]
        cat_label = ", ".join(dict.fromkeys(labels))  # deduplicate, preserve order
        description = f"{cat_label} service" + (f" by {company}" if company else "")
        # Construct a URL from the domain for Disconnect entries.
        url = f"https://{domain}"
        return {"company": company, "description": description, "url": url}

    # 2. Partner databases — have company name + category.
    for config in PARTNER_CATEGORIES:
        db = get_partner_database(config.file)
        for name, entry in db.items():
            entry_domain = (entry.url or "").replace("https://", "").replace("http://", "").rstrip("/").split("/")[0].removeprefix("www.")
            if entry_domain and (entry_domain == domain or entry_domain == url_mod.get_base_domain(domain)):
                cat_label = config.category.replace("-", " ").title()
                description = f"{cat_label} service"
                url = entry.url or f"https://{domain}"
                return {"company": name.title(), "description": description, "url": url}

    # 3. Tracker-domains — minimal info (block/cookieblock).
    if is_known_tracker_domain(domain):
        return {"company": None, "description": "Known tracking domain", "url": None}

    return {"company": None, "description": None, "url": None}


def get_storage_key_hint(key: str) -> dict[str, str | None]:
    """Return a brief hint for a storage key from the tracking-storage database.

    Matches *key* against the compiled tracking-storage patterns.
    Returns a dict with ``setBy`` and ``description`` (either may
    be ``None`` when no match is found).
    """
    patterns = get_tracking_storage_patterns()
    for pattern, desc, set_by, _purpose in patterns:
        if pattern.search(key):
            return {"setBy": set_by, "description": desc}
    return {"setBy": None, "description": None}


# ============================================================================
# Partner Data Loading
# ============================================================================


def _load_partner_database(filename: str) -> dict[str, partners.PartnerEntry]:
    """Load partner database from a JSON file."""
    raw: dict[str, dict[str, Any]] = _load_json(f"partners/{filename}")
    return {
        key: partners.PartnerEntry(
            concerns=val.get("concerns", []),
            aliases=val.get("aliases", []),
            url=val.get("url", ""),
            privacy_url=val.get("privacy_url", ""),
            gvl_ids=val.get("gvl_ids", []),
            atp_ids=val.get("atp_ids", []),
        )
        for key, val in raw.items()
    }


@functools.cache
def get_partner_database(filename: str) -> dict[str, partners.PartnerEntry]:
    """Get a partner database by filename (loaded once per filename and cached)."""
    result = _load_partner_database(filename)
    log.info("Partner database loaded", {"file": filename, "entries": len(result)})
    return result


# ============================================================================
# Partner Category Configuration
# ============================================================================

PARTNER_CATEGORIES: list[partners.PartnerCategoryConfig] = [
    partners.PartnerCategoryConfig(
        file="data-brokers.json",
        risk_level="critical",
        category="data-broker",
        reason="Known data broker that aggregates and sells personal information",
        risk_score=10,
    ),
    partners.PartnerCategoryConfig(
        file="identity-trackers.json",
        risk_level="critical",
        category="identity-resolution",
        reason="Identity resolution service that links your identity across devices and sites",
        risk_score=9,
    ),
    partners.PartnerCategoryConfig(
        file="session-replay.json",
        risk_level="high",
        category="cross-site-tracking",
        reason="Session replay service that records your interactions on the site",
        risk_score=8,
    ),
    partners.PartnerCategoryConfig(
        file="ad-networks.json",
        risk_level="high",
        category="advertising",
        reason="Major advertising network that tracks across many websites",
        risk_score=7,
    ),
    partners.PartnerCategoryConfig(
        file="mobile-sdk-trackers.json",
        risk_level="high",
        category="cross-site-tracking",
        reason="Mobile SDK tracker embedded in apps for user tracking",
        risk_score=7,
    ),
    partners.PartnerCategoryConfig(
        file="analytics-trackers.json",
        risk_level="medium",
        category="analytics",
        reason="Analytics or marketing platform that collects behavioral data",
        risk_score=5,
    ),
    partners.PartnerCategoryConfig(
        file="social-trackers.json",
        risk_level="medium",
        category="social-media",
        reason="Social media tracker that monitors social interactions across sites",
        risk_score=5,
    ),
    partners.PartnerCategoryConfig(
        file="consent-providers.json",
        risk_level="medium",
        category="personalization",
        reason="Consent management platform that may share consent signals",
        risk_score=4,
    ),
]


# ============================================================================
# GDPR / TCF Reference Data Loading
# ============================================================================


@functools.cache
def get_tcf_purposes() -> dict[str, Any]:
    """Get TCF purpose taxonomy (loaded once and cached).

    Returns the IAB TCF v2.2 purpose definitions including
    purposes, special purposes, features, special features,
    and data declarations.
    """
    result: dict[str, Any] = _load_json("consent/tcf-purposes.json")
    return result


@functools.cache
def get_consent_cookies() -> dict[str, Any]:
    """Get known consent-state cookie definitions (loaded once and cached).

    Returns data about TCF cookies, CMP-specific consent cookies,
    and patterns for identifying consent-related cookies.
    """
    result: dict[str, Any] = _load_json("consent/consent-cookies.json")
    return result


@functools.cache
def get_gdpr_reference() -> dict[str, Any]:
    """Get GDPR and ePrivacy reference data (loaded once and cached).

    Returns comprehensive reference information about GDPR lawful
    bases, key principles, data subject rights, ePrivacy cookie
    categories, and TCF overview.
    """
    result: dict[str, Any] = _load_json("consent/gdpr-reference.json")
    return result


@functools.cache
def get_gvl_vendors() -> dict[str, str]:
    """Get the IAB Global Vendor List name mapping (loaded once and cached).

    Returns a dict mapping vendor ID (string) to vendor name
    for all vendors in the IAB GVL.  Entries that carry
    embedded enrichment data are normalised to plain name
    strings for backward compatibility.
    """
    raw = _load_gvl_raw()
    return {vid: (entry["name"] if isinstance(entry, dict) else entry) for vid, entry in raw.items()}


@functools.cache
def get_gvl_vendor_details() -> dict[str, dict[str, Any]]:
    """Get the enriched IAB GVL vendor details (loaded once and cached).

    Returns a dict mapping vendor ID (string) to a dict with
    at least a ``name`` key.  Enriched entries also carry
    ``category``, ``concerns``, and ``url``.
    """
    raw = _load_gvl_raw()
    result: dict[str, dict[str, Any]] = {}
    for vid, entry in raw.items():
        if isinstance(entry, dict):
            result[vid] = entry
        else:
            result[vid] = {"name": entry}
    return result


@functools.cache
def _load_gvl_raw() -> dict[str, Any]:
    """Load the raw GVL vendors map (mixed str / dict entries)."""
    data: dict[str, Any] = _load_json("consent/gvl-vendors.json")
    vendors: dict[str, Any] = data.get("vendors", {})
    return vendors


@functools.cache
def get_google_atp_providers() -> dict[str, dict[str, Any]]:
    """Get the Google ATP provider list (loaded once and cached).

    Returns a dict mapping provider ID (string) to a dict
    with ``name`` and ``policyUrl`` keys.  Enriched entries
    may also carry ``category``, ``concerns``, and ``url``.
    """
    data: dict[str, Any] = _load_json("consent/google-atp-providers.json")
    result: dict[str, dict[str, Any]] = data.get("providers", {})
    return result


# ============================================================================
# Media Group Profile Loading
# ============================================================================


@functools.cache
def get_media_groups() -> dict[str, partners.MediaGroupProfile]:
    """Get media group profiles (loaded once and cached).

    Returns a dictionary mapping lowercase group names to
    their MediaGroupProfile containing ownership, properties,
    domains, key vendors, and privacy characteristics.
    """
    raw: dict[str, dict[str, Any]] = _load_json("publishers/media-groups.json")
    result = {key: partners.MediaGroupProfile(**val) for key, val in raw.items()}
    log.info("Media groups loaded", {"count": len(result)})
    return result


def find_media_group_by_domain(domain: str) -> tuple[str, partners.MediaGroupProfile] | None:
    """Look up a media group by one of its known domains.

    Strips a leading ``www.`` prefix and also tries the
    registrable base domain (e.g. ``example.co.uk`` from
    ``sub.example.co.uk``) so callers don't need to
    normalise beforehand.

    Args:
        domain: A domain name (e.g. 'thesun.co.uk') to search for.

    Returns:
        A tuple of (group_name, profile) if found, or None.
    """
    domain_lower = domain.lower().strip()
    # Build candidate set: original, without www., and base domain.
    candidates = {domain_lower}
    if domain_lower.startswith("www."):
        candidates.add(domain_lower[4:])
    candidates.add(url_mod.get_base_domain(domain_lower))

    for name, profile in get_media_groups().items():
        if candidates & set(profile.domains):
            return (name, profile)
    return None


# ============================================================================
# Consent Platform Profile Loading
# ============================================================================


@functools.cache
def load_consent_platforms() -> dict[str, Any]:
    """Load consent platform profiles (loaded once and cached).

    Returns a dictionary mapping platform keys to
    ``ConsentPlatformProfile`` instances.  The profiles are
    constructed by the ``consent.platform_detection`` module;
    this function returns the raw dict-based intermediate
    representation to avoid circular imports.
    """
    from src.consent.platform_detection import ConsentPlatformProfile

    raw: dict[str, Any] = _load_json("consent/consent-platforms.json")
    platforms: dict[str, Any] = raw.get("platforms", {})
    result = {key: ConsentPlatformProfile(key, data) for key, data in platforms.items()}
    log.info("Consent platforms loaded", {"count": len(result)})
    return result


# ============================================================================
# Media Group Context for LLM Prompts
# ============================================================================


def build_media_group_context(analyzed_url: str) -> str:
    """Build media group context for LLM prompts.

    Extracts the domain from *analyzed_url*, looks up a
    matching media group profile, and returns a formatted
    reference section.  Returns an empty string when no
    match is found.

    Args:
        analyzed_url: The full URL being analysed.

    Returns:
        Formatted media group context section, or ``""``.
    """
    hostname = url_mod.extract_domain(analyzed_url)
    base_domain = url_mod.get_base_domain(hostname)
    result = find_media_group_by_domain(base_domain)
    if result is None:
        return ""

    name, profile = result
    lines: list[str] = [
        "",
        "## Publisher / Media Group Context (Prior Research)",
        "",
        f"This site belongs to **{profile.parent}** (group key: {name}).",
        f"- Privacy policy: {profile.privacy_policy}",
        f"- Consent platform: {profile.consent_platform}",
        f"- Properties ({len(profile.properties)}): {', '.join(profile.properties[:10])}",
        f"- Known domains: {', '.join(profile.domains[:10])}",
        "",
        "### Key Vendors",
    ]
    for vendor in profile.key_vendors:
        lines.append(f"- {vendor}")
    lines.append("")
    lines.append("### Privacy Characteristics")
    for char in profile.privacy_characteristics:
        lines.append(f"- {char}")
    lines.append("")
    return "\n".join(lines)
