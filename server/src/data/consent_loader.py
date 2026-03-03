"""GDPR, TCF, and consent reference data loaders."""

from __future__ import annotations

import functools
from typing import Any

from src.data import _base
from src.models import consent

# ── TCF / GDPR reference ───────────────────────────────────


@functools.cache
def get_tcf_purposes() -> dict[str, Any]:
    """Get TCF purpose taxonomy (loaded once and cached).

    Returns the IAB TCF v2.2 purpose definitions including
    purposes, special purposes, features, special features,
    and data declarations.
    """
    result: dict[str, Any] = _base._load_json("consent/tcf-purposes.json")
    return result


@functools.cache
def get_consent_cookies() -> dict[str, Any]:
    """Get known consent-state cookie definitions (loaded once and cached).

    Returns data about TCF cookies, CMP-specific consent cookies,
    and patterns for identifying consent-related cookies.
    """
    result: dict[str, Any] = _base._load_json("consent/consent-cookies.json")
    return result


@functools.cache
def get_gdpr_reference() -> dict[str, Any]:
    """Get GDPR and ePrivacy reference data (loaded once and cached).

    Returns comprehensive reference information about GDPR lawful
    bases, key principles, data subject rights, ePrivacy cookie
    categories, and TCF overview.
    """
    result: dict[str, Any] = _base._load_json("consent/gdpr-reference.json")
    return result


# ── GVL vendors ─────────────────────────────────────────────


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
    data: dict[str, Any] = _base._load_json("consent/gvl-vendors.json")
    vendors: dict[str, Any] = data.get("vendors", {})
    return vendors


# ── Google ATP providers ────────────────────────────────────


@functools.cache
def get_google_atp_providers() -> dict[str, dict[str, Any]]:
    """Get the Google ATP provider list (loaded once and cached).

    Returns a dict mapping provider ID (string) to a dict
    with ``name`` and ``policyUrl`` keys.  Enriched entries
    may also carry ``category``, ``concerns``, and ``url``.
    """
    data: dict[str, Any] = _base._load_json("consent/google-atp-providers.json")
    result: dict[str, dict[str, Any]] = data.get("providers", {})
    return result


# ── Consent platform profiles ──────────────────────────────


@functools.cache
def load_consent_platforms() -> dict[str, consent.ConsentPlatformProfile]:
    """Load consent platform profiles (loaded once and cached).

    Returns a dictionary mapping platform keys to
    ``ConsentPlatformProfile`` instances.
    """
    raw: dict[str, Any] = _base._load_json("consent/consent-platforms.json")
    platforms: dict[str, Any] = raw.get("platforms", {})
    result = {key: consent.ConsentPlatformProfile(key, data) for key, data in platforms.items()}
    _base.log.info("Consent platforms loaded", {"count": len(result)})
    return result
