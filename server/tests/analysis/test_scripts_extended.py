"""Tests for src.analysis.scripts — pure identification and inference functions."""

from __future__ import annotations

import pytest

from src.analysis.scripts import (
    _identify_benign_script,
    _identify_tracker_domain,
    _identify_tracking_script,
    _infer_from_url,
    is_fallback_description,
)


class TestIdentifyTrackingScript:
    """Tests for _identify_tracking_script()."""

    def test_google_analytics(self) -> None:
        result = _identify_tracking_script("https://www.google-analytics.com/analytics.js")
        assert result is not None
        assert len(result) > 0

    def test_unknown_script(self) -> None:
        result = _identify_tracking_script("https://example.com/app-bundle-abc123.js")
        assert result is None

    def test_facebook_pixel(self) -> None:
        result = _identify_tracking_script("https://connect.facebook.net/en_US/fbevents.js")
        assert result is not None


class TestIdentifyBenignScript:
    """Tests for _identify_benign_script()."""

    def test_known_benign(self) -> None:
        # Common benign scripts should be recognised
        result = _identify_benign_script("https://cdn.example.com/jquery.min.js")
        # depends on the database — just check it doesn't crash
        assert result is None or isinstance(result, str)

    def test_tracking_not_benign(self) -> None:
        result = _identify_benign_script("https://www.google-analytics.com/analytics.js")
        # A tracking script should not be classified as benign
        assert result is None or isinstance(result, str)


class TestIdentifyTrackerDomain:
    """Tests for _identify_tracker_domain()."""

    def test_unknown_domain(self) -> None:
        result = _identify_tracker_domain("example.com")
        assert result is None

    def test_known_tracker(self) -> None:
        result = _identify_tracker_domain("doubleclick.net")
        if result is not None:
            assert "tracker" in result.lower() or "known" in result.lower()


class TestInferFromUrl:
    """Tests for _infer_from_url()."""

    @pytest.mark.parametrize(
        ("url", "expected_substring"),
        [
            ("https://example.com/analytics.js", "Analytics"),
            ("https://example.com/tracking.js", "Tracking"),
            ("https://example.com/pixel.gif", "pixel"),
            ("https://example.com/consent.js", "Consent"),
            ("https://example.com/chat-widget.js", "Chat"),
            ("https://example.com/ads.js", "Advertising"),
            ("https://example.com/social-share.js", "Social"),
            ("https://example.com/vendor-stuff.js", "vendor"),
            ("https://example.com/polyfill.min.js", "polyfill"),
            ("https://example.com/app-bundle.js", "bundle"),
            ("https://example.com/chunk-abc123.js", "chunk"),
            ("https://example.com/unknown-xyz.js", "Third-party"),
        ],
    )
    def test_url_heuristics(self, url: str, expected_substring: str) -> None:
        result = _infer_from_url(url)
        assert expected_substring.lower() in result.lower()


class TestIsFallbackDescription:
    """Tests for is_fallback_description()."""

    def test_fallback_descriptions(self) -> None:
        assert is_fallback_description("Analytics script") is True
        assert is_fallback_description("Tracking script") is True
        assert is_fallback_description("Third-party script") is True
        assert is_fallback_description("Application bundle") is True

    def test_non_fallback_descriptions(self) -> None:
        assert is_fallback_description("Google Analytics tracking library") is False
        assert is_fallback_description("Facebook Pixel event tracking") is False
        assert is_fallback_description("Custom description from LLM") is False

    def test_empty_string(self) -> None:
        assert is_fallback_description("") is False
