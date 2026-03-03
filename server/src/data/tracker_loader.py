"""Tracker data loaders.

Scripts, cookies, storage keys, domains, CNAME cloaking,
and Disconnect tracking-protection list.
"""

from __future__ import annotations

import functools
import re
from typing import Any

from src.data import _base
from src.models import partners
from src.utils import url

# ── Script patterns ─────────────────────────────────────────


@functools.cache
def get_tracking_scripts() -> list[partners.ScriptPattern]:
    """Get tracking scripts database (loaded once and cached)."""
    return _base._load_script_patterns("tracking-scripts.json")


@functools.cache
def get_benign_scripts() -> list[partners.ScriptPattern]:
    """Get benign scripts database (loaded once and cached)."""
    return _base._load_script_patterns("benign-scripts.json")


# ── Tracking cookies ────────────────────────────────────────


@functools.cache
def get_tracking_cookies() -> dict[str, Any]:
    """Get known tracking cookie definitions (loaded once and cached).

    Returns the full JSON structure containing cookie entries,
    risk levels, and privacy notes.
    """
    result: dict[str, Any] = _base._load_json("trackers/tracking-cookies.json")
    return result


@functools.cache
def get_tracking_cookie_patterns() -> tuple[tuple[re.Pattern[str], str, str, str], ...]:
    """Build compiled regex patterns from the tracking cookies data.

    Returns a tuple of tuples: ``(pattern, description, set_by, purpose)``.
    Cached after the first call to avoid re-compiling regexes.
    """
    data = get_tracking_cookies()
    entries: dict[str, dict[str, str]] = data.get("cookies", {})
    return tuple(
        (
            re.compile(entry["pattern"], re.I),
            entry["description"],
            entry["setBy"],
            entry["purpose"],
        )
        for key, entry in entries.items()
        if isinstance(entry, dict)
    )


def get_tracking_cookie_risk_map() -> dict[str, str]:
    """Return purpose -> risk-level mapping from the tracking cookies data."""
    data = get_tracking_cookies()
    result: dict[str, str] = data.get("risk_levels", {})
    return result


def get_tracking_cookie_privacy_map() -> dict[str, str]:
    """Return purpose -> privacy-note mapping from the tracking cookies data."""
    data = get_tracking_cookies()
    result: dict[str, str] = data.get("privacy_notes", {})
    return result


def get_tracking_cookie_vendor_index() -> dict[str, dict[str, Any]]:
    """Return setBy -> vendor metadata from the tracking cookies data.

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


# ── Tracking storage keys ───────────────────────────────────


@functools.cache
def get_tracking_storage_keys() -> dict[str, Any]:
    """Get known tracking storage key definitions (loaded once and cached).

    Returns the full JSON structure containing storage key entries,
    risk levels, and privacy notes.
    """
    result: dict[str, Any] = _base._load_json("trackers/tracking-storage.json")
    return result


@functools.cache
def get_tracking_storage_patterns() -> tuple[tuple[re.Pattern[str], str, str, str], ...]:
    """Build compiled regex patterns from the tracking storage keys data.

    Returns a tuple of tuples: ``(pattern, description, set_by, purpose)``.
    Cached after the first call to avoid re-compiling regexes.
    """
    data = get_tracking_storage_keys()
    entries: dict[str, dict[str, str]] = data.get("keys", {})
    return tuple(
        (
            re.compile(entry["pattern"], re.I),
            entry["description"],
            entry["setBy"],
            entry["purpose"],
        )
        for key, entry in entries.items()
        if isinstance(entry, dict)
    )


def get_tracking_storage_risk_map() -> dict[str, str]:
    """Return purpose -> risk-level mapping from the tracking storage data."""
    data = get_tracking_storage_keys()
    result: dict[str, str] = data.get("risk_levels", {})
    return result


def get_tracking_storage_privacy_map() -> dict[str, str]:
    """Return purpose -> privacy-note mapping from the tracking storage data."""
    data = get_tracking_storage_keys()
    result: dict[str, str] = data.get("privacy_notes", {})
    return result


def get_tracking_storage_vendor_index() -> dict[str, dict[str, Any]]:
    """Return setBy -> vendor metadata from the tracking storage data.

    Each entry may contain ``category``, ``gvl_ids``, ``atp_ids``,
    ``url``, and ``concerns``.
    """
    data = get_tracking_storage_keys()
    result: dict[str, dict[str, Any]] = data.get("vendors", {})
    return result


# ── Tracker domains ─────────────────────────────────────────


@functools.cache
def get_tracker_domains() -> dict[str, str]:
    """Get known tracker domain classifications.

    Returns a dictionary mapping domain names to their
    classification (``"block"`` or ``"cookieblock"``).
    """
    data: dict[str, Any] = _base._load_json("trackers/tracker-domains.json")
    result: dict[str, str] = data.get("domains", {})
    _base.log.info("Tracker domains loaded", {"count": len(result)})
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

    base = url.get_base_domain(domain)
    return base in tracker_domains


# ── CNAME cloaking ──────────────────────────────────────────


@functools.cache
def get_cname_domains() -> dict[str, str]:
    """Get CNAME-cloaked domain mappings.

    Returns a dictionary mapping first-party subdomains to
    their actual tracker CNAME destinations.  Used to detect
    CNAME cloaking where trackers disguise themselves as
    first-party domains.
    """
    data: dict[str, Any] = _base._load_json(
        "trackers/cname-domains.json",
    )
    # Remove the _description metadata key
    result = {k: v for k, v in data.items() if not k.startswith("_")}
    _base.log.info("CNAME domains loaded", {"count": len(result)})
    return result


def get_cname_target(domain: str) -> str | None:
    """Look up the CNAME target for a potentially cloaked domain.

    Args:
        domain: A domain/subdomain to check for cloaking.

    Returns:
        The real tracker domain, or ``None`` if not cloaked.
    """
    return get_cname_domains().get(domain)


# ── Disconnect tracking protection ──────────────────────────


@functools.cache
def get_disconnect_services() -> dict[str, dict[str, Any]]:
    """Get Disconnect tracker domain categories.

    Returns a dictionary mapping domain names to their
    tracking category and operating company.  Categories
    include Advertising, Analytics, FingerprintingInvasive,
    Social, Cryptomining, and others.
    """
    data: dict[str, Any] = _base._load_json(
        "trackers/disconnect-services.json",
    )
    result: dict[str, dict[str, Any]] = data.get("domains", {})
    _base.log.info("Disconnect services loaded", {"count": len(result)})
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

    base = url.get_base_domain(domain)
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

    # Look up each domain, dedup by (domain, category, company).
    matches: dict[str, list[tuple[str, str]]] = {}
    seen: set[str] = set()
    for domain in third_party_domains:
        if domain in seen:
            continue
        seen.add(domain)
        info = services.get(domain)
        if not info:
            base = url.get_base_domain(domain)
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

    Examples: ``FingerprintingGeneral`` -> ``Fingerprinting``,
    ``Advertising`` -> ``Advertising``.
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
