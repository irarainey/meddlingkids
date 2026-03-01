"""Tests for vendor name resolution from TC String and AC String IDs."""

from __future__ import annotations

from unittest.mock import patch

from src.analysis.vendor_lookup import (
    AcResolutionResult,
    ResolvedAcProvider,
    ResolvedVendor,
    VendorResolutionResult,
    resolve_ac_providers,
    resolve_gvl_vendors,
)

# ── GVL Vendor Resolution ───────────────────────────────────────


_FAKE_GVL: dict[str, str] = {
    "1": "Exponential Interactive",
    "2": "Captify Technologies",
    "10": "Index Exchange",
}


class TestResolveGvlVendors:
    """Tests for resolve_gvl_vendors()."""

    @patch("src.analysis.vendor_lookup.loader.get_gvl_vendors", return_value=_FAKE_GVL)
    def test_known_vendors_resolved(self, _mock: object) -> None:
        result = resolve_gvl_vendors([2, 1])
        assert result == VendorResolutionResult(
            resolved=[
                ResolvedVendor(id=1, name="Exponential Interactive"),
                ResolvedVendor(id=2, name="Captify Technologies"),
            ],
            unresolved_count=0,
        )

    @patch("src.analysis.vendor_lookup.loader.get_gvl_vendors", return_value=_FAKE_GVL)
    def test_unknown_vendor_excluded_and_counted(self, _mock: object) -> None:
        result = resolve_gvl_vendors([999])
        assert result["resolved"] == []
        assert result["unresolved_count"] == 1

    @patch("src.analysis.vendor_lookup.loader.get_gvl_vendors", return_value=_FAKE_GVL)
    def test_mixed_known_and_unknown(self, _mock: object) -> None:
        result = resolve_gvl_vendors([10, 500, 1])
        assert result["resolved"] == [
            ResolvedVendor(id=1, name="Exponential Interactive"),
            ResolvedVendor(id=10, name="Index Exchange"),
        ]
        assert result["unresolved_count"] == 1

    @patch("src.analysis.vendor_lookup.loader.get_gvl_vendors", return_value=_FAKE_GVL)
    def test_empty_list_returns_empty(self, _mock: object) -> None:
        result = resolve_gvl_vendors([])
        assert result["resolved"] == []
        assert result["unresolved_count"] == 0

    @patch("src.analysis.vendor_lookup.loader.get_gvl_vendors", return_value=_FAKE_GVL)
    def test_results_sorted_by_id(self, _mock: object) -> None:
        result = resolve_gvl_vendors([10, 2, 1])
        ids = [v["id"] for v in result["resolved"]]
        assert ids == [1, 2, 10]

    @patch("src.analysis.vendor_lookup.loader.get_gvl_vendors", return_value=_FAKE_GVL)
    def test_duplicates_deduplicated(self, _mock: object) -> None:
        result = resolve_gvl_vendors([1, 1, 1, 2, 2, 10])
        assert len(result["resolved"]) == 3
        assert result["unresolved_count"] == 0


# ── AC Provider Resolution ──────────────────────────────────────


_FAKE_ATP: dict[str, dict[str, str]] = {
    "89": {"name": "Meta", "policyUrl": "https://facebook.com/privacy"},
    "42": {"name": "Taboola", "policyUrl": "https://taboola.com/privacy"},
    "100": {"name": "No Policy Provider"},
}


class TestResolveAcProviders:
    """Tests for resolve_ac_providers()."""

    @patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_known_providers_resolved(self, _mock: object) -> None:
        result = resolve_ac_providers([89, 42])
        assert result == AcResolutionResult(
            resolved=[
                ResolvedAcProvider(id=42, name="Taboola", policy_url="https://taboola.com/privacy"),
                ResolvedAcProvider(id=89, name="Meta", policy_url="https://facebook.com/privacy"),
            ],
            unresolved_count=0,
        )

    @patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_unknown_provider_excluded_and_counted(self, _mock: object) -> None:
        result = resolve_ac_providers([7777])
        assert result["resolved"] == []
        assert result["unresolved_count"] == 1

    @patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_missing_policy_url_defaults_to_empty(self, _mock: object) -> None:
        result = resolve_ac_providers([100])
        assert result["resolved"] == [
            ResolvedAcProvider(id=100, name="No Policy Provider", policy_url=""),
        ]
        assert result["unresolved_count"] == 0

    @patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_empty_list_returns_empty(self, _mock: object) -> None:
        result = resolve_ac_providers([])
        assert result["resolved"] == []
        assert result["unresolved_count"] == 0

    @patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_results_sorted_by_id(self, _mock: object) -> None:
        result = resolve_ac_providers([89, 42, 100])
        ids = [p["id"] for p in result["resolved"]]
        assert ids == [42, 89, 100]

    @patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_duplicates_deduplicated(self, _mock: object) -> None:
        result = resolve_ac_providers([89, 89, 89, 42, 42])
        assert len(result["resolved"]) == 2
        assert result["unresolved_count"] == 0

    @patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_mixed_known_unknown_with_duplicates(self, _mock: object) -> None:
        result = resolve_ac_providers([89, 1, 1, 1, 42, 5, 5])
        assert len(result["resolved"]) == 2
        assert result["unresolved_count"] == 2  # IDs 1 and 5
