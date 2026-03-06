"""Extended tests for src.data — consent and media data loaders."""

from __future__ import annotations

from src.data import consent_loader, media_loader


class TestConsentLoader:
    """Tests for consent reference data loaders."""

    def test_gvl_vendor_details_structure(self) -> None:
        details = consent_loader.get_gvl_vendor_details()
        assert isinstance(details, dict)
        assert len(details) > 0
        for _vid, entry in list(details.items())[:5]:
            assert "name" in entry
            assert isinstance(entry["name"], str)

    def test_google_atp_providers(self) -> None:
        providers = consent_loader.get_google_atp_providers()
        assert isinstance(providers, dict)
        assert len(providers) > 0
        for _pid, pdata in list(providers.items())[:5]:
            assert "name" in pdata

    def test_consent_platforms_loaded(self) -> None:
        platforms = consent_loader.load_consent_platforms()
        assert isinstance(platforms, dict)
        assert len(platforms) >= 10

    def test_gvl_vendors_are_strings(self) -> None:
        vendors = consent_loader.get_gvl_vendors()
        assert isinstance(vendors, dict)
        for _vid, name in list(vendors.items())[:5]:
            assert isinstance(name, str)


class TestMediaLoader:
    """Tests for media group loader."""

    def test_find_known_domain(self) -> None:
        result = media_loader.find_media_group_by_domain("bbc.co.uk")
        # May or may not find BBC depending on data; just test no crash
        if result is not None:
            group_name, profile = result
            assert isinstance(group_name, str)
            assert hasattr(profile, "consent_platform")

    def test_find_unknown_domain(self) -> None:
        result = media_loader.find_media_group_by_domain("totally-unknown-domain-xyz123.com")
        assert result is None
