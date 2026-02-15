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
    return {key: partners.PartnerEntry(concerns=val.get("concerns", []), aliases=val.get("aliases", [])) for key, val in raw.items()}


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
