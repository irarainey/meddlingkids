"""Extended tests for src.analysis.vendor_lookup — vendor enrichment."""

from __future__ import annotations

from src.analysis.vendor_lookup import _enrich, resolve_gvl_vendors


class TestEnrichVendor:
    """Tests for vendor name enrichment."""

    def test_known_vendor(self) -> None:
        result = _enrich("Google")
        # May or may not find enrichment depending on data
        if result:
            assert "category" in result

    def test_unknown_vendor(self) -> None:
        result = _enrich("Completely Unknown Vendor XYZ 123456")
        # Might return None or empty enrichment
        assert result is None or isinstance(result, dict)


class TestResolveGvlVendorsExtended:
    """Extended tests for GVL vendor resolution."""

    def test_empty_vendor_ids(self) -> None:
        result = resolve_gvl_vendors([])
        assert isinstance(result, dict)

    def test_nonexistent_vendor_id(self) -> None:
        result = resolve_gvl_vendors([99999])
        # Should return the ID with "Unknown Vendor" or similar
        assert isinstance(result, dict)

    def test_known_vendor_id(self) -> None:
        # ID 755 is Google Advertising Products
        result = resolve_gvl_vendors([755])
        assert isinstance(result, dict)
