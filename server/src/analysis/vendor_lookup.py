"""Vendor name resolution for TC String and AC String IDs.

Resolves numeric vendor IDs from the IAB TC String and Google
AC String to human-readable company names using bundled data:

- **IAB GVL** (Global Vendor List): maps TC String vendor IDs
  to names of IAB-registered ad-tech vendors.
- **Google ATP** (Ad Technology Providers): maps AC String
  provider IDs to names of non-IAB vendors consented via
  Google's Additional Consent Mode.

Resolved vendors are optionally enriched with classification
metadata (category and privacy concerns) from the partner
databases and Disconnect tracking-protection list.
"""

from __future__ import annotations

import functools
import re
from typing import Any, TypedDict

from src.data import loader

# ── Enrichment types ────────────────────────────────────────────


class VendorEnrichment(TypedDict, total=False):
    """Optional classification metadata attached to a vendor."""

    category: str
    concerns: list[str]
    url: str


class ResolvedVendor(TypedDict, total=False):
    """A vendor ID resolved to a name with optional enrichment."""

    id: int
    name: str
    url: str
    policy_url: str
    category: str
    concerns: list[str]
    purposes: list[int]


class ResolvedAcProvider(TypedDict, total=False):
    """A Google ATP provider resolved to name, URL, and enrichment."""

    id: int
    name: str
    policy_url: str
    url: str
    category: str
    concerns: list[str]


class VendorResolutionResult(TypedDict):
    """Result of vendor ID resolution with known/unknown split."""

    resolved: list[ResolvedVendor]
    unresolved_count: int


class AcResolutionResult(TypedDict):
    """Result of AC provider ID resolution with known/unknown split."""

    resolved: list[ResolvedAcProvider]
    unresolved_count: int


# ── Name normalisation ──────────────────────────────────────────

_CORP_SUFFIXES = re.compile(
    r"\s*,?\s*(?:inc\.?|ltd\.?|llc|gmbh|s\.?a\.?s?\.?|"
    r"b\.?v\.?|corporation|co\.?\s*ltd\.?|limited|plc|ag|"
    r"pty|corp|oy|d/?b/?a\s+\S+|international).*$",
    re.IGNORECASE,
)


def _normalise_keys(name: str) -> list[str]:
    """Return candidate lookup keys for a vendor name.

    Generates multiple normalised forms so that e.g.
    ``"Criteo SA"`` matches the partner DB entry ``"criteo"``.
    """
    lower = name.lower().strip()
    short = _CORP_SUFFIXES.sub("", lower).strip()
    candidates = [lower, short]
    words = lower.split()
    if len(words) > 1:
        candidates.append(words[0])
    return candidates


# ── Enrichment index (built once, cached) ───────────────────────


_ENRICHMENT_CATEGORY_MAP: dict[str, str] = {
    "ad-networks.json": "Ad Network",
    "analytics-trackers.json": "Analytics",
    "consent-providers.json": "Consent Provider",
    "data-brokers.json": "Data Broker",
    "identity-trackers.json": "Identity Tracker",
    "mobile-sdk-trackers.json": "Mobile SDK",
    "session-replay.json": "Session Replay",
    "social-trackers.json": "Social Tracker",
}

_EnrichmentIndexes = tuple[
    dict[str, VendorEnrichment],
    dict[int, VendorEnrichment],
    dict[int, VendorEnrichment],
]


@functools.cache
def _build_enrichment_indexes() -> _EnrichmentIndexes:
    """Build all three enrichment indexes (name, GVL-ID, ATP-ID).

    Called once and cached via ``@functools.cache``.

    Returns:
        A tuple of ``(name_index, gvl_id_index, atp_id_index)``.
    """
    index: dict[str, VendorEnrichment] = {}
    gvl_idx: dict[int, VendorEnrichment] = {}
    atp_idx: dict[int, VendorEnrichment] = {}

    # Partner databases — provide category + concerns.
    for cfg in loader.PARTNER_CATEGORIES:
        db = loader.get_partner_database(cfg.file)
        label = _ENRICHMENT_CATEGORY_MAP.get(cfg.file, "Unknown")
        for name, entry in db.items():
            enrichment = VendorEnrichment(
                category=label,
                concerns=entry.concerns[:3],
            )
            if entry.url:
                enrichment["url"] = entry.url
            index[name.lower()] = enrichment
            for alias in entry.aliases:
                index[alias.lower()] = enrichment

            # ID-based indexes from cross-reference fields.
            for gvl_id in entry.gvl_ids:
                gvl_idx[gvl_id] = enrichment
            for atp_id in entry.atp_ids:
                atp_idx[atp_id] = enrichment

    # Disconnect services — provide category only (by company).
    disc = loader.get_disconnect_services()
    for _domain, info in disc.items():
        company = (info.get("company") or "").lower().strip()
        if not company or company in index:
            continue
        raw_cat = info.get("category", "Tracking")
        if isinstance(raw_cat, list):
            cat_label = ", ".join(raw_cat)
        else:
            cat_label = str(raw_cat)
        index[company] = VendorEnrichment(category=cat_label)

    return index, gvl_idx, atp_idx


def _get_enrichment_index() -> dict[str, VendorEnrichment]:
    """Return the name → enrichment index."""
    return _build_enrichment_indexes()[0]


def _get_gvl_id_index() -> dict[int, VendorEnrichment]:
    """Return the GVL-ID → enrichment index."""
    return _build_enrichment_indexes()[1]


def _get_atp_id_index() -> dict[int, VendorEnrichment]:
    """Return the ATP-ID → enrichment index."""
    return _build_enrichment_indexes()[2]


def _enrich(name: str) -> VendorEnrichment | None:
    """Look up enrichment metadata for a vendor name."""
    index = _get_enrichment_index()
    for key in _normalise_keys(name):
        if key in index:
            return index[key]
    return None


def _enrich_by_gvl_id(vid: int) -> VendorEnrichment | None:
    """Look up enrichment metadata by GVL vendor ID."""
    return _get_gvl_id_index().get(vid)


def _enrich_by_atp_id(pid: int) -> VendorEnrichment | None:
    """Look up enrichment metadata by ATP provider ID."""
    return _get_atp_id_index().get(pid)


def _enrichment_from_entry(entry: dict[str, Any]) -> VendorEnrichment | None:
    """Extract inline enrichment from a GVL/ATP entry dict.

    If the entry carries ``category`` (and optionally ``concerns``
    and ``url``), build a ``VendorEnrichment`` from it directly.
    """
    cat = entry.get("category")
    if not cat:
        return None
    enrichment = VendorEnrichment(category=cat)
    concerns = entry.get("concerns")
    if concerns:
        enrichment["concerns"] = concerns
    url = entry.get("url")
    if url:
        enrichment["url"] = url
    return enrichment


# ── Public API ──────────────────────────────────────────────────


def resolve_gvl_vendors(
    vendor_ids: list[int],
) -> VendorResolutionResult:
    """Resolve IAB GVL vendor IDs to company names.

    Each resolved vendor is enriched with ``category`` and
    ``concerns``.  Enrichment is resolved in priority order:

    1. Inline metadata embedded in the GVL data file.
    2. ID-based lookup from partner cross-reference IDs.
    3. Fuzzy name matching against partner and Disconnect DBs.

    Args:
        vendor_ids: List of vendor IDs from the TC String
            (``vendorConsents`` or ``vendorLegitimateInterests``).

    Returns:
        A ``VendorResolutionResult`` containing a list of
        resolved vendors (only those found in the GVL) and
        a count of unresolved IDs.
    """
    gvl_names = loader.get_gvl_vendors()
    gvl_details = loader.get_gvl_vendor_details()
    resolved: list[ResolvedVendor] = []
    unresolved = 0
    for vid in sorted(set(vendor_ids)):
        name = gvl_names.get(str(vid))
        if name:
            vendor = ResolvedVendor(id=vid, name=name)

            # Try enrichment sources in priority order.
            detail = gvl_details.get(str(vid), {})
            enrichment = _enrichment_from_entry(detail) or _enrich_by_gvl_id(vid) or _enrich(name)
            if enrichment:
                vendor["category"] = enrichment["category"]
                if "concerns" in enrichment:
                    vendor["concerns"] = enrichment["concerns"]
                if "url" in enrichment:
                    vendor["url"] = enrichment["url"]

            # Attach GVL-sourced metadata.
            if "policyUrl" in detail:
                vendor["policy_url"] = detail["policyUrl"]
            if "purposes" in detail:
                vendor["purposes"] = detail["purposes"]
            resolved.append(vendor)
        else:
            unresolved += 1
    return VendorResolutionResult(
        resolved=resolved,
        unresolved_count=unresolved,
    )


def resolve_ac_providers(
    provider_ids: list[int],
) -> AcResolutionResult:
    """Resolve Google ATP provider IDs to company names.

    Each resolved provider is enriched with ``category`` and
    ``concerns``.  Enrichment is resolved in priority order:

    1. Inline metadata embedded in the ATP data file.
    2. ID-based lookup from partner cross-reference IDs.
    3. Fuzzy name matching against partner and Disconnect DBs.

    Args:
        provider_ids: List of provider IDs from the AC String
            (``vendorIds``).

    Returns:
        An ``AcResolutionResult`` containing a list of resolved
        providers (only those found in the Google ATP list) and
        a count of unresolved IDs.
    """
    atp = loader.get_google_atp_providers()
    resolved: list[ResolvedAcProvider] = []
    unresolved = 0
    for pid in sorted(set(provider_ids)):
        entry = atp.get(str(pid))
        if entry:
            provider = ResolvedAcProvider(
                id=pid,
                name=entry["name"],
                policy_url=entry.get("policyUrl", ""),
            )

            # Try enrichment sources in priority order.
            enrichment = _enrichment_from_entry(entry) or _enrich_by_atp_id(pid) or _enrich(entry["name"])
            if enrichment:
                provider["category"] = enrichment["category"]
                if "concerns" in enrichment:
                    provider["concerns"] = enrichment["concerns"]
                if "url" in enrichment:
                    provider["url"] = enrichment["url"]
            resolved.append(provider)
        else:
            unresolved += 1
    return AcResolutionResult(
        resolved=resolved,
        unresolved_count=unresolved,
    )
