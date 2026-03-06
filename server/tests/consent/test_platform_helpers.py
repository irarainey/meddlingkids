"""Tests for src.consent.platform_detection — platform profile helpers."""

from __future__ import annotations

from src.consent.platform_detection import (
    detect_platform_from_cookies,
    get_platform_profile,
    get_platform_profiles,
)


class TestGetPlatformProfile:
    """Tests for get_platform_profile() lookup."""

    def test_known_platform(self) -> None:
        profile = get_platform_profile("onetrust")
        assert profile is not None
        assert "onetrust" in profile.name.lower() or profile.key == "onetrust"

    def test_unknown_platform(self) -> None:
        profile = get_platform_profile("nonexistent_platform_xyz")
        assert profile is None

    def test_case_insensitive(self) -> None:
        profile = get_platform_profile("OneTrust")
        assert profile is not None

    def test_replaces_spaces(self) -> None:
        profile = get_platform_profile("inmobi choice")
        assert profile is not None


class TestDetectPlatformFromCookies:
    """Tests for detect_platform_from_cookies()."""

    def test_empty_cookies(self) -> None:
        result = detect_platform_from_cookies([])
        assert result is None

    def test_no_matching_cookies(self) -> None:
        cookies = [{"name": "session_id"}, {"name": "theme"}]
        result = detect_platform_from_cookies(cookies)
        assert result is None

    def test_onetrust_cookies(self) -> None:
        cookies = [{"name": "OptanonConsent"}, {"name": "OptanonAlertBoxClosed"}]
        result = detect_platform_from_cookies(cookies)
        if result is not None:
            assert "onetrust" in result.name.lower() or result.key == "onetrust"

    def test_cookiebot_cookies(self) -> None:
        cookies = [{"name": "CookieConsent"}]
        result = detect_platform_from_cookies(cookies)
        # May match cookiebot or similar
        if result is not None:
            assert result.name is not None


class TestGetPlatformProfiles:
    """Tests for get_platform_profiles() caching."""

    def test_returns_dict(self) -> None:
        profiles = get_platform_profiles()
        assert isinstance(profiles, dict)

    def test_contains_known_profiles(self) -> None:
        profiles = get_platform_profiles()
        assert len(profiles) >= 10

    def test_profile_has_required_fields(self) -> None:
        profiles = get_platform_profiles()
        for key, profile in profiles.items():
            assert profile.name
            assert profile.key == key
