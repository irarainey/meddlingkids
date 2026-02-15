"""
Data loader for tracker, partner, and GDPR/TCF reference databases.
Loads JSON files and compiles patterns into regex objects.

The JSON data files live alongside this module in partners/, trackers/,
and gdpr/ subdirectories.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from src.models import partners

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
    """
    full_path = _DATA_DIR / relative_path
    if not full_path.exists():
        raise FileNotFoundError(f"Data file not found: {relative_path}")
    with open(full_path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as exc:
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
    return [
        partners.ScriptPattern(
            pattern=entry["pattern"],
            description=entry["description"],
            compiled=re.compile(entry["pattern"], re.IGNORECASE),
        )
        for entry in raw
    ]


_tracking_scripts: list[partners.ScriptPattern] | None = None
_benign_scripts: list[partners.ScriptPattern] | None = None


def get_tracking_scripts() -> list[partners.ScriptPattern]:
    """Get tracking scripts database (lazy loaded and cached)."""
    global _tracking_scripts
    if _tracking_scripts is None:
        _tracking_scripts = _load_script_patterns("tracking-scripts.json")
    return _tracking_scripts


def get_benign_scripts() -> list[partners.ScriptPattern]:
    """Get benign scripts database (lazy loaded and cached)."""
    global _benign_scripts
    if _benign_scripts is None:
        _benign_scripts = _load_script_patterns("benign-scripts.json")
    return _benign_scripts


# ============================================================================
# Partner Data Loading
# ============================================================================


_partner_database_cache: dict[str, dict[str, partners.PartnerEntry]] = {}


def _load_partner_database(filename: str) -> dict[str, partners.PartnerEntry]:
    """Load partner database from a JSON file."""
    raw: dict[str, dict[str, Any]] = _load_json(f"partners/{filename}")
    return {
        key: partners.PartnerEntry(
            concerns=val.get("concerns", []),
            aliases=val.get("aliases", []),
            url=val.get("url", ""),
        )
        for key, val in raw.items()
    }


def get_partner_database(filename: str) -> dict[str, partners.PartnerEntry]:
    """Get a partner database by filename (lazy loaded and cached)."""
    if filename not in _partner_database_cache:
        _partner_database_cache[filename] = _load_partner_database(filename)
    return _partner_database_cache[filename]


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
        file="consent-platforms.json",
        risk_level="medium",
        category="personalization",
        reason="Consent management platform that may share consent signals",
        risk_score=4,
    ),
]


# ============================================================================
# GDPR / TCF Reference Data Loading
# ============================================================================

_tcf_purposes_cache: dict[str, Any] | None = None
_consent_cookies_cache: dict[str, Any] | None = None
_gdpr_reference_cache: dict[str, Any] | None = None


def get_tcf_purposes() -> dict[str, Any]:
    """Get TCF purpose taxonomy (lazy loaded and cached).

    Returns the IAB TCF v2.2 purpose definitions including
    purposes, special purposes, features, special features,
    and data declarations.
    """
    global _tcf_purposes_cache
    if _tcf_purposes_cache is None:
        _tcf_purposes_cache = _load_json("gdpr/tcf-purposes.json")
    return _tcf_purposes_cache


def get_consent_cookies() -> dict[str, Any]:
    """Get known consent-state cookie definitions (lazy loaded and cached).

    Returns data about TCF cookies, CMP-specific consent cookies,
    and patterns for identifying consent-related cookies.
    """
    global _consent_cookies_cache
    if _consent_cookies_cache is None:
        _consent_cookies_cache = _load_json("gdpr/consent-cookies.json")
    return _consent_cookies_cache


def get_gdpr_reference() -> dict[str, Any]:
    """Get GDPR and ePrivacy reference data (lazy loaded and cached).

    Returns comprehensive reference information about GDPR lawful
    bases, key principles, data subject rights, ePrivacy cookie
    categories, and TCF overview.
    """
    global _gdpr_reference_cache
    if _gdpr_reference_cache is None:
        _gdpr_reference_cache = _load_json("gdpr/gdpr-reference.json")
    return _gdpr_reference_cache


def get_tcf_purpose_name(purpose_id: int) -> str:
    """Look up a TCF purpose name by its numeric ID.

    Returns the purpose name or 'Unknown purpose {id}' if not found.
    """
    purposes = get_tcf_purposes().get("purposes", {})
    entry = purposes.get(str(purpose_id))
    if entry:
        return str(entry["name"])
    return f"Unknown purpose {purpose_id}"


def get_consent_cookie_names() -> list[str]:
    """Get the list of known consent-state cookie name patterns.

    Returns patterns that can be used to identify cookies set by
    CMPs rather than tracking cookies.
    """
    data = get_consent_cookies()
    return list(data.get("consent_cookie_name_patterns", []))


# ============================================================================
# Media Group Profile Loading
# ============================================================================

_media_groups_cache: dict[str, partners.MediaGroupProfile] | None = None


def get_media_groups() -> dict[str, partners.MediaGroupProfile]:
    """Get media group profiles (lazy loaded and cached).

    Returns a dictionary mapping lowercase group names to
    their MediaGroupProfile containing ownership, properties,
    domains, key vendors, and privacy characteristics.
    """
    global _media_groups_cache
    if _media_groups_cache is None:
        raw: dict[str, dict[str, Any]] = _load_json("publishers/media-groups.json")
        _media_groups_cache = {key: partners.MediaGroupProfile(**val) for key, val in raw.items()}
    return _media_groups_cache


def find_media_group_by_domain(domain: str) -> tuple[str, partners.MediaGroupProfile] | None:
    """Look up a media group by one of its known domains.

    Args:
        domain: A domain name (e.g. 'thesun.co.uk') to search for.

    Returns:
        A tuple of (group_name, profile) if found, or None.
    """
    domain_lower = domain.lower().strip()
    for name, profile in get_media_groups().items():
        if domain_lower in profile.domains:
            return (name, profile)
    return None


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
    from src.utils import url as url_mod  # Local import to avoid circular dependency

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
        "The following is background information gathered from prior research "
        "into this publisher's privacy practices. It represents what was "
        "previously known about this media group BEFORE the current analysis. "
        "Use it as a reference — not as a definitive or exhaustive list.",
        "",
        f"This site belongs to **{profile.parent}** (group key: {name}).",
        f"- Privacy policy: {profile.privacy_policy}",
        f"- Consent platform: {profile.consent_platform}",
        f"- Properties ({len(profile.properties)}): {', '.join(profile.properties[:10])}",
        f"- Known domains: {', '.join(profile.domains[:10])}",
        "",
        "### Key Vendors (previously identified through privacy policy research)",
        "These vendors were identified in prior reviews of this publisher's privacy policy and consent dialogs:",
    ]
    for vendor in profile.key_vendors:
        lines.append(f"- {vendor}")
    lines.append("")
    lines.append("### Privacy Characteristics (previously documented)")
    for char in profile.privacy_characteristics:
        lines.append(f"- {char}")
    lines.append("")
    lines.append(
        "### How to use this context\n"
        "- Cross-reference the trackers and cookies you observe in the "
        "current scan against the vendors listed above.\n"
        "- If you detect a vendor from the list, note that it was previously "
        "known to be used by this publisher — this is expected behaviour.\n"
        "- If you detect trackers or vendors NOT in the list, highlight them "
        "as potentially new or undisclosed.\n"
        "- If a vendor from the list is NOT observed in the current scan, "
        "do not assume it is absent — it may load conditionally, on other "
        "pages, or via server-side integration.\n"
        "- Use the privacy characteristics to provide richer context in "
        "your analysis (e.g. ownership structure, consent platform, "
        "known data-sharing arrangements)."
    )
    return "\n".join(lines)
