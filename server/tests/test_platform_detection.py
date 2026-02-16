"""Tests for src.consent.platform_detection — CMP detection and strategies."""

from __future__ import annotations

from typing import ClassVar

import pytest

from src.consent import platform_detection
from src.consent.overlay_cache import CachedOverlay

# ────────────────────────────────────────────────────────────
# Profile loading
# ────────────────────────────────────────────────────────────


class TestGetPlatformProfiles:
    """Verify profile loading and caching."""

    def test_returns_non_empty_dict(self) -> None:
        profiles = platform_detection.get_platform_profiles()
        assert isinstance(profiles, dict)
        assert len(profiles) >= 10  # We ship at least 19 profiles

    def test_cached(self) -> None:
        a = platform_detection.get_platform_profiles()
        b = platform_detection.get_platform_profiles()
        assert a is b

    def test_all_values_are_profiles(self) -> None:
        for key, profile in platform_detection.get_platform_profiles().items():
            assert isinstance(profile, platform_detection.ConsentPlatformProfile)
            assert profile.key == key

    def test_sourcepoint_present(self) -> None:
        profiles = platform_detection.get_platform_profiles()
        assert "sourcepoint" in profiles

    def test_onetrust_present(self) -> None:
        profiles = platform_detection.get_platform_profiles()
        assert "onetrust" in profiles


class TestGetPlatformProfile:
    """Verify single-profile lookup."""

    def test_exact_key(self) -> None:
        profile = platform_detection.get_platform_profile("sourcepoint")
        assert profile is not None
        assert profile.name == "Sourcepoint"

    def test_case_insensitive(self) -> None:
        profile = platform_detection.get_platform_profile("OneTrust")
        assert profile is not None
        assert profile.key == "onetrust"

    def test_space_to_underscore(self) -> None:
        profile = platform_detection.get_platform_profile("quantcast choice")
        assert profile is not None
        assert profile.key == "quantcast_choice"

    def test_missing_key_returns_none(self) -> None:
        assert platform_detection.get_platform_profile("nonexistent_cmp") is None


# ────────────────────────────────────────────────────────────
# ConsentPlatformProfile construction
# ────────────────────────────────────────────────────────────


class TestConsentPlatformProfile:
    """Verify profile construction from raw data."""

    def test_basic_fields(self) -> None:
        data = {
            "name": "TestCMP",
            "vendor": "Test Inc.",
            "privacy_url": "https://test.com/privacy",
            "tcf_registered": True,
            "description": "A test CMP",
            "notes": "Testing notes",
        }
        profile = platform_detection.ConsentPlatformProfile("test_cmp", data)
        assert profile.key == "test_cmp"
        assert profile.name == "TestCMP"
        assert profile.vendor == "Test Inc."
        assert profile.privacy_url == "https://test.com/privacy"
        assert profile.tcf_registered is True
        assert profile.description == "A test CMP"
        assert profile.notes == "Testing notes"

    def test_list_fields(self) -> None:
        data = {
            "iframe_patterns": ["cdn.test.com"],
            "container_selectors": ["#test-banner"],
            "js_apis": ["window.__test"],
            "cookie_indicators": ["test_consent"],
            "accept_button_patterns": ["button.accept"],
            "reject_button_patterns": ["button.reject"],
            "manage_button_patterns": ["button.manage"],
        }
        profile = platform_detection.ConsentPlatformProfile("test_cmp", data)
        assert profile.iframe_patterns == ["cdn.test.com"]
        assert profile.container_selectors == ["#test-banner"]
        assert profile.js_apis == ["window.__test"]
        assert profile.cookie_indicators == ["test_consent"]
        assert profile.accept_button_patterns == ["button.accept"]
        assert profile.reject_button_patterns == ["button.reject"]
        assert profile.manage_button_patterns == ["button.manage"]

    def test_defaults_for_missing_fields(self) -> None:
        profile = platform_detection.ConsentPlatformProfile("x", {})
        assert profile.key == "x"
        assert profile.name == "x"
        assert profile.vendor == ""
        assert profile.privacy_url == ""
        assert profile.tcf_registered is False
        assert profile.description == ""
        assert profile.iframe_patterns == []
        assert profile.container_selectors == []
        assert profile.js_apis == []
        assert profile.cookie_indicators == []
        assert profile.accept_button_patterns == []
        assert profile.reject_button_patterns == []
        assert profile.manage_button_patterns == []
        assert profile.notes == ""


# ────────────────────────────────────────────────────────────
# Profile data quality checks
# ────────────────────────────────────────────────────────────


class TestProfileDataQuality:
    """Verify the shipped consent-platforms.json has good data."""

    EXPECTED_PLATFORMS: ClassVar[list[str]] = [
        "sourcepoint",
        "onetrust",
        "quantcast_choice",
        "cookiebot",
        "didomi",
        "trustarc",
        "usercentrics",
        "complianz",
        "consentmanager",
        "iubenda",
        "funding_choices",
        "osano",
        "termly",
        "cookie_law_info",
        "admiral",
        "axeptio",
        "sirdata",
        "crownpeak",
        "commander_act",
    ]

    @pytest.mark.parametrize("key", EXPECTED_PLATFORMS)
    def test_platform_exists(self, key: str) -> None:
        profile = platform_detection.get_platform_profile(key)
        assert profile is not None, f"Platform '{key}' not found in data file"

    @pytest.mark.parametrize("key", EXPECTED_PLATFORMS)
    def test_platform_has_name(self, key: str) -> None:
        profile = platform_detection.get_platform_profile(key)
        assert profile is not None
        assert profile.name, f"Platform '{key}' has no name"

    @pytest.mark.parametrize("key", EXPECTED_PLATFORMS)
    def test_platform_has_container_selectors(self, key: str) -> None:
        profile = platform_detection.get_platform_profile(key)
        assert profile is not None
        assert len(profile.container_selectors) > 0, f"Platform '{key}' has no container_selectors"

    @pytest.mark.parametrize("key", [k for k in EXPECTED_PLATFORMS if k != "admiral"])
    def test_platform_has_accept_patterns(self, key: str) -> None:
        profile = platform_detection.get_platform_profile(key)
        assert profile is not None
        assert len(profile.accept_button_patterns) > 0, f"Platform '{key}' has no accept_button_patterns"

    def test_admiral_has_partial_accept_patterns(self) -> None:
        """Admiral has best-effort selectors for FC-style deployments."""
        profile = platform_detection.get_platform_profile("admiral")
        assert profile is not None
        assert len(profile.accept_button_patterns) > 0
        assert all("admiral" in s for s in profile.accept_button_patterns), "Admiral selectors must be scoped under div[id^='admiral-']"

    @pytest.mark.parametrize("key", EXPECTED_PLATFORMS)
    def test_platform_has_cookie_indicators(self, key: str) -> None:
        profile = platform_detection.get_platform_profile(key)
        assert profile is not None
        assert len(profile.cookie_indicators) > 0, f"Platform '{key}' has no cookie_indicators"

    def test_sourcepoint_has_iframe_patterns(self) -> None:
        """Sourcepoint is iframe-based — must have iframe patterns."""
        profile = platform_detection.get_platform_profile("sourcepoint")
        assert profile is not None
        assert len(profile.iframe_patterns) > 0

    def test_consentmanager_has_iframe_patterns(self) -> None:
        """consentmanager renders in an iframe — must have iframe patterns."""
        profile = platform_detection.get_platform_profile("consentmanager")
        assert profile is not None
        assert len(profile.iframe_patterns) > 0
        assert any("consentmanager" in p for p in profile.iframe_patterns)

    def test_onetrust_has_no_iframes(self) -> None:
        """OneTrust renders in the main frame — no iframe patterns."""
        profile = platform_detection.get_platform_profile("onetrust")
        assert profile is not None
        assert profile.iframe_patterns == []


# ────────────────────────────────────────────────────────────
# Cookie-based detection
# ────────────────────────────────────────────────────────────


class TestDetectPlatformFromCookies:
    """Verify CMP detection from cookies."""

    def test_empty_cookies_returns_none(self) -> None:
        assert platform_detection.detect_platform_from_cookies([]) is None

    def test_no_cmp_cookies_returns_none(self) -> None:
        cookies = [
            {"name": "session_id", "value": "abc"},
            {"name": "theme", "value": "dark"},
        ]
        assert platform_detection.detect_platform_from_cookies(cookies) is None

    def test_sourcepoint_cookies(self) -> None:
        cookies = [
            {"name": "consentUUID", "value": "abc-123"},
            {"name": "sp_consent", "value": "true"},
        ]
        result = platform_detection.detect_platform_from_cookies(cookies)
        assert result is not None
        assert result.key == "sourcepoint"

    def test_onetrust_cookies(self) -> None:
        cookies = [
            {"name": "OptanonConsent", "value": "some-value"},
            {"name": "OptanonAlertBoxClosed", "value": "2024-01-01"},
        ]
        result = platform_detection.detect_platform_from_cookies(cookies)
        assert result is not None
        assert result.key == "onetrust"

    def test_cookiebot_cookies(self) -> None:
        cookies = [
            {"name": "CookieConsent", "value": "true"},
            {"name": "CookieConsentBulkTicket", "value": "xyz"},
        ]
        result = platform_detection.detect_platform_from_cookies(cookies)
        assert result is not None
        assert result.key == "cookiebot"

    def test_didomi_cookies(self) -> None:
        cookies = [
            {"name": "didomi_token", "value": "token-value"},
        ]
        result = platform_detection.detect_platform_from_cookies(cookies)
        assert result is not None
        assert result.key == "didomi"

    def test_quantcast_cookies(self) -> None:
        cookies = [
            {"name": "euconsent-v2", "value": "tc-string"},
            {"name": "addtl_consent", "value": "additional"},
        ]
        result = platform_detection.detect_platform_from_cookies(cookies)
        assert result is not None
        assert result.key == "quantcast_choice"

    def test_most_hits_wins(self) -> None:
        """When cookies match multiple CMPs, the one with most hits wins."""
        # OneTrust has 4 cookies vs 1 for another
        cookies = [
            {"name": "OptanonConsent", "value": "v"},
            {"name": "OptanonAlertBoxClosed", "value": "v"},
            {"name": "eupubconsent-v2", "value": "v"},
            {"name": "OTAdditionalConsentString", "value": "v"},
        ]
        result = platform_detection.detect_platform_from_cookies(cookies)
        assert result is not None
        assert result.key == "onetrust"


# ────────────────────────────────────────────────────────────
# Domain-based detection (via media groups)
# ────────────────────────────────────────────────────────────


class TestDetectPlatformFromDomain:
    """Verify CMP detection from media group domain lookup."""

    def test_unknown_domain_returns_none(self) -> None:
        result = platform_detection.detect_platform_from_domain("random-unknown-site.xyz")
        assert result is None

    def test_reach_plc_domain_returns_sourcepoint(self) -> None:
        """mirror.co.uk is a Reach plc site using Sourcepoint."""
        result = platform_detection.detect_platform_from_domain("mirror.co.uk")
        assert result is not None
        assert result.key == "sourcepoint"

    def test_dmg_media_domain_returns_onetrust(self) -> None:
        """dailymail.co.uk is a DMG Media site using OneTrust."""
        result = platform_detection.detect_platform_from_domain("dailymail.co.uk")
        assert result is not None
        assert result.key == "onetrust"

    def test_bristol247_domain_returns_consentmanager(self) -> None:
        """bristol247.com is an independent site using consentmanager."""
        result = platform_detection.detect_platform_from_domain("bristol247.com")
        assert result is not None
        assert result.key == "consentmanager"


# ────────────────────────────────────────────────────────────
# Media group CMP map coverage
# ────────────────────────────────────────────────────────────


class TestMediaGroupCmpMap:
    """Verify the _MEDIA_GROUP_CMP_MAP covers expected entries."""

    def test_sourcepoint_in_map(self) -> None:
        assert "sourcepoint" in platform_detection._MEDIA_GROUP_CMP_MAP

    def test_onetrust_in_map(self) -> None:
        assert "onetrust" in platform_detection._MEDIA_GROUP_CMP_MAP

    def test_quantcast_variants_in_map(self) -> None:
        assert "quantcast choice" in platform_detection._MEDIA_GROUP_CMP_MAP
        assert "quantcast" in platform_detection._MEDIA_GROUP_CMP_MAP

    def test_all_values_are_valid_profile_keys(self) -> None:
        profiles = platform_detection.get_platform_profiles()
        for label, key in platform_detection._MEDIA_GROUP_CMP_MAP.items():
            assert key in profiles, f"CMP map value '{key}' (from label '{label}') is not a valid profile key"

    def test_all_media_group_cmps_resolve(self) -> None:
        """Every non-custom consent_platform in media-groups.json must resolve
        through _MEDIA_GROUP_CMP_MAP to a valid consent platform profile."""
        from src.data import loader

        groups = loader.get_media_groups()
        cmp_map = platform_detection._MEDIA_GROUP_CMP_MAP

        for group_name, profile in groups.items():
            cmp = (profile.consent_platform or "").lower().strip()
            if cmp.startswith("custom") or not cmp:
                continue
            key = cmp_map.get(cmp)
            if key is None:
                for mk, pk in cmp_map.items():
                    if mk in cmp:
                        key = pk
                        break
            assert key is not None, (
                f"Media group '{group_name}' has consent_platform '{profile.consent_platform}' which is not in _MEDIA_GROUP_CMP_MAP"
            )
            resolved = platform_detection.get_platform_profile(key)
            assert resolved is not None, (
                f"Media group '{group_name}' maps to profile key '{key}' which does not exist in consent-platforms.json"
            )

    def test_media_group_cmp_names_match_profile_names(self) -> None:
        """The consent_platform display name in media-groups.json must match
        the profile name in consent-platforms.json for consistency."""
        from src.data import loader

        groups = loader.get_media_groups()
        cmp_map = platform_detection._MEDIA_GROUP_CMP_MAP
        profiles = platform_detection.get_platform_profiles()

        for group_name, profile in groups.items():
            cmp = (profile.consent_platform or "").lower().strip()
            if cmp.startswith("custom") or not cmp:
                continue
            key = cmp_map.get(cmp)
            if key and key in profiles:
                assert profile.consent_platform == profiles[key].name, (
                    f"Media group '{group_name}' uses '{profile.consent_platform}' but consent profile uses '{profiles[key].name}'"
                )


# ────────────────────────────────────────────────────────────
# CachedOverlay consent_platform field
# ────────────────────────────────────────────────────────────


class TestCachedOverlayConsentPlatform:
    """Verify the consent_platform field on CachedOverlay."""

    def test_default_is_none(self) -> None:
        overlay = CachedOverlay(
            overlay_type="cookie-consent",
            button_text="Accept",
        )
        assert overlay.consent_platform is None

    def test_set_to_platform_key(self) -> None:
        overlay = CachedOverlay(
            overlay_type="cookie-consent",
            button_text="Accept All",
            consent_platform="sourcepoint",
        )
        assert overlay.consent_platform == "sourcepoint"

    def test_round_trip_serialisation(self) -> None:
        overlay = CachedOverlay(
            overlay_type="cookie-consent",
            button_text="Accept",
            css_selector="#accept-btn",
            locator_strategy="css",
            consent_platform="onetrust",
        )
        data = overlay.model_dump()
        restored = CachedOverlay.model_validate(data)
        assert restored.consent_platform == "onetrust"

    def test_backward_compat_missing_field(self) -> None:
        """Old cache entries that lack consent_platform still load."""
        data = {
            "overlay_type": "cookie-consent",
            "button_text": "Accept cookies",
        }
        overlay = CachedOverlay.model_validate(data)
        assert overlay.consent_platform is None


# ────────────────────────────────────────────────────────────
# Page-based detection (DOM + iframes)
# ────────────────────────────────────────────────────────────


class TestDetectPlatformFromPage:
    """Verify CMP detection from page DOM and iframes."""

    @pytest.mark.asyncio
    async def test_detects_main_frame_container(self) -> None:
        """Detects a CMP from container selectors in the main frame."""
        from unittest.mock import AsyncMock, MagicMock

        page = AsyncMock()
        page.frames = [page.main_frame]

        # Simulate a visible #onetrust-banner-sdk element
        locator = AsyncMock()
        locator.is_visible = AsyncMock(return_value=True)
        first_mock = MagicMock()
        first_mock.first = locator
        page.locator = MagicMock(return_value=first_mock)

        result = await platform_detection.detect_platform_from_page(page)
        # Should match one of the profiles with that selector
        assert result is not None

    @pytest.mark.asyncio
    async def test_detects_iframe_based_cmp(self) -> None:
        """Detects a CMP by matching iframe URL to iframe_patterns."""
        from unittest.mock import AsyncMock, MagicMock

        main_frame = MagicMock()
        main_frame.url = "https://www.example.com/"

        consent_frame = MagicMock()
        consent_frame.url = "https://delivery.consentmanager.net/delivery/cmp.php"

        # Set up a visible container inside the iframe
        iframe_locator = AsyncMock()
        iframe_locator.is_visible = AsyncMock(return_value=True)
        iframe_first = MagicMock()
        iframe_first.first = iframe_locator
        consent_frame.locator = MagicMock(return_value=iframe_first)

        page = AsyncMock()
        page.main_frame = main_frame
        page.frames = [main_frame, consent_frame]

        # Main frame selectors should not be visible
        main_locator = AsyncMock()
        main_locator.is_visible = AsyncMock(return_value=False)
        main_first = MagicMock()
        main_first.first = main_locator
        page.locator = MagicMock(return_value=main_first)

        result = await platform_detection.detect_platform_from_page(page)
        assert result is not None
        assert result.key == "consentmanager"

    @pytest.mark.asyncio
    async def test_detects_iframe_url_without_container(self) -> None:
        """Detects a CMP from iframe URL even when container selectors fail."""
        from unittest.mock import AsyncMock, MagicMock

        main_frame = MagicMock()
        main_frame.url = "https://www.example.com/"

        consent_frame = MagicMock()
        consent_frame.url = "https://delivery.consentmanager.net/delivery/cmp.php"

        # Container selector raises exception in iframe
        iframe_locator = AsyncMock()
        iframe_locator.is_visible = AsyncMock(side_effect=Exception("timeout"))
        iframe_first = MagicMock()
        iframe_first.first = iframe_locator
        consent_frame.locator = MagicMock(return_value=iframe_first)

        page = AsyncMock()
        page.main_frame = main_frame
        page.frames = [main_frame, consent_frame]

        # Main frame selectors not visible
        main_locator = AsyncMock()
        main_locator.is_visible = AsyncMock(return_value=False)
        main_first = MagicMock()
        main_first.first = main_locator
        page.locator = MagicMock(return_value=main_first)

        result = await platform_detection.detect_platform_from_page(page)
        assert result is not None
        assert result.key == "consentmanager"

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self) -> None:
        """Returns None when no CMP is detected in DOM or iframes."""
        from unittest.mock import AsyncMock, MagicMock

        main_frame = MagicMock()
        main_frame.url = "https://www.example.com/"

        page = AsyncMock()
        page.main_frame = main_frame
        page.frames = [main_frame]

        # All selectors fail
        locator = AsyncMock()
        locator.is_visible = AsyncMock(return_value=False)
        first_mock = MagicMock()
        first_mock.first = locator
        page.locator = MagicMock(return_value=first_mock)

        result = await platform_detection.detect_platform_from_page(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_ignores_non_matching_iframes(self) -> None:
        """Iframes that don't match any platform's iframe_patterns are skipped."""
        from unittest.mock import AsyncMock, MagicMock

        main_frame = MagicMock()
        main_frame.url = "https://www.example.com/"

        ad_frame = MagicMock()
        ad_frame.url = "https://ads.example.com/banner"

        page = AsyncMock()
        page.main_frame = main_frame
        page.frames = [main_frame, ad_frame]

        # Main frame selectors not visible
        locator = AsyncMock()
        locator.is_visible = AsyncMock(return_value=False)
        first_mock = MagicMock()
        first_mock.first = locator
        page.locator = MagicMock(return_value=first_mock)

        result = await platform_detection.detect_platform_from_page(page)
        assert result is None
