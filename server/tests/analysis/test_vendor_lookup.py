"""Tests for vendor name resolution from TC String and AC String IDs."""

from __future__ import annotations

from collections.abc import Generator
from unittest import mock

import pytest

from src.analysis import vendor_lookup

# ── GVL Vendor Resolution ───────────────────────────────────────


_FAKE_GVL: dict[str, str] = {
    "1": "Exponential Interactive",
    "2": "Captify Technologies",
    "10": "Index Exchange",
}

_FAKE_GVL_DETAILS: dict[str, dict[str, object]] = {
    "1": {"name": "Exponential Interactive"},
    "2": {"name": "Captify Technologies"},
    "10": {"name": "Index Exchange"},
}

_FAKE_ENRICHMENT: dict[str, vendor_lookup.VendorEnrichment] = {
    "captify technologies": vendor_lookup.VendorEnrichment(
        category="Ad Network",
        concerns=["Contextual and semantic advertising"],
        url="https://captify.tech",
    ),
    "index exchange": vendor_lookup.VendorEnrichment(
        category="Ad Network",
        concerns=["Ad marketplace"],
        url="https://indexexchange.com",
    ),
    "meta": vendor_lookup.VendorEnrichment(
        category="Ad Network",
        concerns=[
            "Facebook pixel on millions of sites",
            "Cross-device tracking",
        ],
        url="https://facebook.com",
    ),
    "taboola": vendor_lookup.VendorEnrichment(
        category="Analytics",
    ),
}


class TestResolveGvlVendors:
    """Tests for resolve_gvl_vendors()."""

    @pytest.fixture(autouse=True)
    def _empty_id_indexes(self) -> Generator[None]:
        """Prevent real data loading via ID-based enrichment lookups."""
        with mock.patch(
            "src.analysis.vendor_lookup._build_enrichment_indexes",
            return_value=({}, {}, {}),
        ):
            yield

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value=_FAKE_ENRICHMENT,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendor_details",
        return_value=_FAKE_GVL_DETAILS,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendors",
        return_value=_FAKE_GVL,
    )
    def test_known_vendors_resolved(
        self,
        _gvl: object,
        _det: object,
        _enr: object,
    ) -> None:
        result = vendor_lookup.resolve_gvl_vendors([2, 1])
        assert result == vendor_lookup.VendorResolutionResult(
            resolved=[
                vendor_lookup.ResolvedVendor(id=1, name="Exponential Interactive"),
                vendor_lookup.ResolvedVendor(
                    id=2,
                    name="Captify Technologies",
                    category="Ad Network",
                    concerns=["Contextual and semantic advertising"],
                    url="https://captify.tech",
                ),
            ],
            unresolved_count=0,
        )

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value={},
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendor_details",
        return_value=_FAKE_GVL_DETAILS,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendors",
        return_value=_FAKE_GVL,
    )
    def test_unknown_vendor_excluded_and_counted(
        self,
        _gvl: object,
        _det: object,
        _enr: object,
    ) -> None:
        result = vendor_lookup.resolve_gvl_vendors([999])
        assert result["resolved"] == []
        assert result["unresolved_count"] == 1

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value=_FAKE_ENRICHMENT,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendor_details",
        return_value=_FAKE_GVL_DETAILS,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendors",
        return_value=_FAKE_GVL,
    )
    def test_mixed_known_and_unknown(
        self,
        _gvl: object,
        _det: object,
        _enr: object,
    ) -> None:
        result = vendor_lookup.resolve_gvl_vendors([10, 500, 1])
        assert len(result["resolved"]) == 2
        assert result["resolved"][1]["category"] == "Ad Network"
        assert result["unresolved_count"] == 1

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value={},
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendor_details",
        return_value=_FAKE_GVL_DETAILS,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendors",
        return_value=_FAKE_GVL,
    )
    def test_empty_list_returns_empty(
        self,
        _gvl: object,
        _det: object,
        _enr: object,
    ) -> None:
        result = vendor_lookup.resolve_gvl_vendors([])
        assert result["resolved"] == []
        assert result["unresolved_count"] == 0

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value={},
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendor_details",
        return_value=_FAKE_GVL_DETAILS,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendors",
        return_value=_FAKE_GVL,
    )
    def test_results_sorted_by_id(
        self,
        _gvl: object,
        _det: object,
        _enr: object,
    ) -> None:
        result = vendor_lookup.resolve_gvl_vendors([10, 2, 1])
        ids = [v["id"] for v in result["resolved"]]
        assert ids == [1, 2, 10]

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value={},
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendor_details",
        return_value=_FAKE_GVL_DETAILS,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendors",
        return_value=_FAKE_GVL,
    )
    def test_duplicates_deduplicated(
        self,
        _gvl: object,
        _det: object,
        _enr: object,
    ) -> None:
        result = vendor_lookup.resolve_gvl_vendors([1, 1, 1, 2, 2, 10])
        assert len(result["resolved"]) == 3
        assert result["unresolved_count"] == 0

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value=_FAKE_ENRICHMENT,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendor_details",
        return_value=_FAKE_GVL_DETAILS,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendors",
        return_value=_FAKE_GVL,
    )
    def test_enrichment_attached_when_matched(
        self,
        _gvl: object,
        _det: object,
        _enr: object,
    ) -> None:
        """Vendors matching the enrichment index get category/concerns/url."""
        result = vendor_lookup.resolve_gvl_vendors([2])
        vendor = result["resolved"][0]
        assert vendor["category"] == "Ad Network"
        assert vendor["concerns"] == [
            "Contextual and semantic advertising",
        ]
        assert vendor["url"] == "https://captify.tech"

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value=_FAKE_ENRICHMENT,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendor_details",
        return_value=_FAKE_GVL_DETAILS,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendors",
        return_value=_FAKE_GVL,
    )
    def test_no_enrichment_when_unmatched(
        self,
        _gvl: object,
        _det: object,
        _enr: object,
    ) -> None:
        """Vendors not in the enrichment index omit extra keys."""
        result = vendor_lookup.resolve_gvl_vendors([1])
        vendor = result["resolved"][0]
        assert "category" not in vendor
        assert "concerns" not in vendor
        assert "url" not in vendor

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value={},
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendor_details",
        return_value={
            "1": {
                "name": "Exponential Interactive",
                "category": "Ad Network",
                "concerns": ["Retargeting"],
                "url": "https://exponential.com",
            },
        },
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendors",
        return_value={"1": "Exponential Interactive"},
    )
    def test_inline_gvl_enrichment_used(
        self,
        _gvl: object,
        _det: object,
        _enr: object,
    ) -> None:
        """Enrichment embedded in GVL data is used when available."""
        result = vendor_lookup.resolve_gvl_vendors([1])
        vendor = result["resolved"][0]
        assert vendor["category"] == "Ad Network"
        assert vendor["concerns"] == ["Retargeting"]
        assert vendor["url"] == "https://exponential.com"

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value={},
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendor_details",
        return_value={
            "1": {
                "name": "Exponential Interactive",
                "category": "Ad Network",
                "policyUrl": "https://exponential.com/privacy",
                "purposes": [1, 2, 3, 4],
            },
        },
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_gvl_vendors",
        return_value={"1": "Exponential Interactive"},
    )
    def test_policy_url_and_purposes_attached(
        self,
        _gvl: object,
        _det: object,
        _enr: object,
    ) -> None:
        """GVL-sourced policyUrl and purposes are attached to resolved vendors."""
        result = vendor_lookup.resolve_gvl_vendors([1])
        vendor = result["resolved"][0]
        assert vendor["policy_url"] == "https://exponential.com/privacy"
        assert vendor["purposes"] == [1, 2, 3, 4]


_FAKE_ATP: dict[str, dict[str, str]] = {
    "89": {"name": "Meta", "policyUrl": "https://facebook.com/privacy"},
    "42": {"name": "Taboola", "policyUrl": "https://taboola.com/privacy"},
    "100": {"name": "No Policy Provider"},
}


class TestResolveAcProviders:
    """Tests for resolve_ac_providers()."""

    @pytest.fixture(autouse=True)
    def _empty_id_indexes(self) -> Generator[None]:
        """Prevent real data loading via ID-based enrichment lookups."""
        with mock.patch(
            "src.analysis.vendor_lookup._build_enrichment_indexes",
            return_value=({}, {}, {}),
        ):
            yield

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value=_FAKE_ENRICHMENT,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_known_providers_resolved(
        self,
        _atp: object,
        _enr: object,
    ) -> None:
        result = vendor_lookup.resolve_ac_providers([89, 42])
        assert result == vendor_lookup.AcResolutionResult(
            resolved=[
                vendor_lookup.ResolvedAcProvider(
                    id=42,
                    name="Taboola",
                    policy_url="https://taboola.com/privacy",
                    category="Analytics",
                ),
                vendor_lookup.ResolvedAcProvider(
                    id=89,
                    name="Meta",
                    policy_url="https://facebook.com/privacy",
                    category="Ad Network",
                    concerns=[
                        "Facebook pixel on millions of sites",
                        "Cross-device tracking",
                    ],
                    url="https://facebook.com",
                ),
            ],
            unresolved_count=0,
        )

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value={},
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_unknown_provider_excluded_and_counted(
        self,
        _atp: object,
        _enr: object,
    ) -> None:
        result = vendor_lookup.resolve_ac_providers([7777])
        assert result["resolved"] == []
        assert result["unresolved_count"] == 1

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value={},
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_missing_policy_url_defaults_to_empty(
        self,
        _atp: object,
        _enr: object,
    ) -> None:
        result = vendor_lookup.resolve_ac_providers([100])
        assert result["resolved"] == [
            vendor_lookup.ResolvedAcProvider(
                id=100,
                name="No Policy Provider",
                policy_url="",
            ),
        ]
        assert result["unresolved_count"] == 0

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value={},
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_empty_list_returns_empty(
        self,
        _atp: object,
        _enr: object,
    ) -> None:
        result = vendor_lookup.resolve_ac_providers([])
        assert result["resolved"] == []
        assert result["unresolved_count"] == 0

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value={},
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_results_sorted_by_id(
        self,
        _atp: object,
        _enr: object,
    ) -> None:
        result = vendor_lookup.resolve_ac_providers([89, 42, 100])
        ids = [p["id"] for p in result["resolved"]]
        assert ids == [42, 89, 100]

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value={},
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_duplicates_deduplicated(
        self,
        _atp: object,
        _enr: object,
    ) -> None:
        result = vendor_lookup.resolve_ac_providers([89, 89, 89, 42, 42])
        assert len(result["resolved"]) == 2
        assert result["unresolved_count"] == 0

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value={},
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_mixed_known_unknown_with_duplicates(
        self,
        _atp: object,
        _enr: object,
    ) -> None:
        result = vendor_lookup.resolve_ac_providers([89, 1, 1, 1, 42, 5, 5])
        assert len(result["resolved"]) == 2
        assert result["unresolved_count"] == 2  # IDs 1 and 5

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value=_FAKE_ENRICHMENT,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_enrichment_attached_to_ac_provider(
        self,
        _atp: object,
        _enr: object,
    ) -> None:
        """ATP providers matching enrichment get category/concerns."""
        result = vendor_lookup.resolve_ac_providers([89])
        provider = result["resolved"][0]
        assert provider["category"] == "Ad Network"
        assert "Facebook pixel" in provider["concerns"][0]

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value=_FAKE_ENRICHMENT,
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value=_FAKE_ATP,
    )
    def test_enrichment_without_concerns(
        self,
        _atp: object,
        _enr: object,
    ) -> None:
        """Disconnect-only enrichment has category but no concerns."""
        result = vendor_lookup.resolve_ac_providers([42])
        provider = result["resolved"][0]
        assert provider["category"] == "Analytics"
        assert "concerns" not in provider

    @mock.patch(
        "src.analysis.vendor_lookup._get_enrichment_index",
        return_value={},
    )
    @mock.patch(
        "src.analysis.vendor_lookup.loader.get_google_atp_providers",
        return_value={
            "50": {
                "name": "InlineVendor",
                "policyUrl": "https://example.com/p",
                "category": "Data Broker",
                "concerns": ["Sells data"],
                "url": "https://inlinevendor.com",
            },
        },
    )
    def test_inline_atp_enrichment_used(
        self,
        _atp: object,
        _enr: object,
    ) -> None:
        """Enrichment embedded in ATP data is used when available."""
        result = vendor_lookup.resolve_ac_providers([50])
        provider = result["resolved"][0]
        assert provider["category"] == "Data Broker"
        assert provider["concerns"] == ["Sells data"]
        assert provider["url"] == "https://inlinevendor.com"


# ── Normalisation Tests ─────────────────────────────────────────


class TestNormaliseKeys:
    """Tests for _normalise_keys() name normalisation."""

    def test_strips_corporate_suffixes(self) -> None:
        keys = vendor_lookup._normalise_keys("Criteo SA")
        assert "criteo" in keys

    def test_lowercase(self) -> None:
        keys = vendor_lookup._normalise_keys("Index Exchange Inc.")
        assert "index exchange inc." in keys
        assert "index exchange" in keys

    def test_single_word_no_extra_keys(self) -> None:
        keys = vendor_lookup._normalise_keys("Quantcast")
        assert "quantcast" in keys
        assert len(keys) == 2  # lowercase + suffix-stripped
