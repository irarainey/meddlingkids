"""
Data loader for tracker and partner databases.
Loads JSON files and compiles patterns into regex objects.

The JSON data files live alongside this module in partners/ and trackers/
subdirectories.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.types.tracking import PartnerCategoryConfig, PartnerEntry, ScriptPattern

# Resolve path to the data directory (same directory as this module)
_DATA_DIR = Path(__file__).resolve().parent

# ============================================================================
# JSON File Loading
# ============================================================================


def _load_json(relative_path: str) -> Any:
    """Load and parse a JSON file relative to the data directory."""
    full_path = _DATA_DIR / relative_path
    with open(full_path, encoding="utf-8") as f:
        return json.load(f)


# ============================================================================
# Script Pattern Loading
# ============================================================================


def _load_script_patterns(filename: str) -> list[ScriptPattern]:
    """Load script patterns from a JSON file."""
    raw: list[dict[str, str]] = _load_json(f"trackers/{filename}")
    return [ScriptPattern(pattern=entry["pattern"], description=entry["description"]) for entry in raw]


_tracking_scripts: list[ScriptPattern] | None = None
_benign_scripts: list[ScriptPattern] | None = None


def get_tracking_scripts() -> list[ScriptPattern]:
    """Get tracking scripts database (lazy loaded and cached)."""
    global _tracking_scripts
    if _tracking_scripts is None:
        _tracking_scripts = _load_script_patterns("tracking-scripts.json")
    return _tracking_scripts


def get_benign_scripts() -> list[ScriptPattern]:
    """Get benign scripts database (lazy loaded and cached)."""
    global _benign_scripts
    if _benign_scripts is None:
        _benign_scripts = _load_script_patterns("benign-scripts.json")
    return _benign_scripts


def match_script_pattern(pattern: ScriptPattern, url: str) -> bool:
    """Test if a URL matches a script pattern."""
    return bool(re.search(pattern.pattern, url, re.IGNORECASE))


# ============================================================================
# Partner Data Loading
# ============================================================================


_partner_database_cache: dict[str, dict[str, PartnerEntry]] = {}


def _load_partner_database(filename: str) -> dict[str, PartnerEntry]:
    """Load partner database from a JSON file."""
    raw: dict[str, dict[str, Any]] = _load_json(f"partners/{filename}")
    return {
        key: PartnerEntry(concerns=val.get("concerns", []), aliases=val.get("aliases", []))
        for key, val in raw.items()
    }


def get_partner_database(filename: str) -> dict[str, PartnerEntry]:
    """Get a partner database by filename (lazy loaded and cached)."""
    if filename not in _partner_database_cache:
        _partner_database_cache[filename] = _load_partner_database(filename)
    return _partner_database_cache[filename]


def get_all_partner_databases(
    categories: list[PartnerCategoryConfig],
) -> dict[str, dict[str, PartnerEntry]]:
    """Get all partner databases keyed by config file name."""
    return {config.file: get_partner_database(config.file) for config in categories}


# ============================================================================
# Partner Category Configuration
# ============================================================================

PARTNER_CATEGORIES: list[PartnerCategoryConfig] = [
    PartnerCategoryConfig(
        file="data-brokers.json",
        risk_level="critical",
        category="data-broker",
        reason="Known data broker that aggregates and sells personal information",
        risk_score=10,
    ),
    PartnerCategoryConfig(
        file="identity-trackers.json",
        risk_level="critical",
        category="identity-resolution",
        reason="Identity resolution service that links your identity across devices and sites",
        risk_score=9,
    ),
    PartnerCategoryConfig(
        file="session-replay.json",
        risk_level="high",
        category="cross-site-tracking",
        reason="Session replay service that records your interactions on the site",
        risk_score=8,
    ),
    PartnerCategoryConfig(
        file="ad-networks.json",
        risk_level="high",
        category="advertising",
        reason="Major advertising network that tracks across many websites",
        risk_score=7,
    ),
    PartnerCategoryConfig(
        file="mobile-sdk-trackers.json",
        risk_level="high",
        category="cross-site-tracking",
        reason="Mobile SDK tracker embedded in apps for user tracking",
        risk_score=7,
    ),
    PartnerCategoryConfig(
        file="analytics-trackers.json",
        risk_level="medium",
        category="analytics",
        reason="Analytics or marketing platform that collects behavioral data",
        risk_score=5,
    ),
    PartnerCategoryConfig(
        file="social-trackers.json",
        risk_level="medium",
        category="social-media",
        reason="Social media tracker that monitors social interactions across sites",
        risk_score=5,
    ),
    PartnerCategoryConfig(
        file="consent-platforms.json",
        risk_level="medium",
        category="personalization",
        reason="Consent management platform that may share consent signals",
        risk_score=4,
    ),
]
