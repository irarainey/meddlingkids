"""Vendor name resolution for TC String and AC String IDs.

Resolves numeric vendor IDs from the IAB TC String and Google
AC String to human-readable company names using bundled data:

- **IAB GVL** (Global Vendor List): maps TC String vendor IDs
  to names of IAB-registered ad-tech vendors.
- **Google ATP** (Ad Technology Providers): maps AC String
  provider IDs to names of non-IAB vendors consented via
  Google's Additional Consent Mode.
"""

from __future__ import annotations

from typing import TypedDict

from src.data import loader


class ResolvedVendor(TypedDict):
    """A vendor ID resolved to a name."""

    id: int
    name: str


class ResolvedAcProvider(TypedDict):
    """A Google ATP provider ID resolved to a name and policy URL."""

    id: int
    name: str
    policy_url: str


class VendorResolutionResult(TypedDict):
    """Result of vendor ID resolution with known/unknown split."""

    resolved: list[ResolvedVendor]
    unresolved_count: int


class AcResolutionResult(TypedDict):
    """Result of AC provider ID resolution with known/unknown split."""

    resolved: list[ResolvedAcProvider]
    unresolved_count: int


def resolve_gvl_vendors(
    vendor_ids: list[int],
) -> VendorResolutionResult:
    """Resolve IAB GVL vendor IDs to company names.

    Args:
        vendor_ids: List of vendor IDs from the TC String
            (``vendorConsents`` or ``vendorLegitimateInterests``).

    Returns:
        A ``VendorResolutionResult`` containing a list of
        resolved vendors (only those found in the GVL) and
        a count of unresolved IDs.
    """
    gvl = loader.get_gvl_vendors()
    resolved: list[ResolvedVendor] = []
    unresolved = 0
    for vid in sorted(set(vendor_ids)):
        name = gvl.get(str(vid))
        if name:
            resolved.append(ResolvedVendor(id=vid, name=name))
        else:
            unresolved += 1
    return VendorResolutionResult(resolved=resolved, unresolved_count=unresolved)


def resolve_ac_providers(
    provider_ids: list[int],
) -> AcResolutionResult:
    """Resolve Google ATP provider IDs to company names.

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
            resolved.append(
                ResolvedAcProvider(
                    id=pid,
                    name=entry["name"],
                    policy_url=entry.get("policyUrl", ""),
                ),
            )
        else:
            unresolved += 1
    return AcResolutionResult(resolved=resolved, unresolved_count=unresolved)
