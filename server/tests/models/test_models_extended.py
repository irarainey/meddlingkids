"""Extended tests for Pydantic models — consent, analysis, browser."""

from __future__ import annotations

import pytest

from src.models import analysis, consent


class TestConsentPartnerValidation:
    """Tests for ConsentPartner name validation."""

    def test_valid_partner_name(self) -> None:
        partner = consent.ConsentPartner(
            name="Google LLC",
            purpose="Analytics",
            data_collected=["pageviews"],
        )
        assert partner.name == "Google LLC"

    def test_strips_whitespace(self) -> None:
        partner = consent.ConsentPartner(
            name="  Google LLC  ",
            purpose="Analytics",
            data_collected=[],
        )
        assert partner.name == "Google LLC"

    def test_rejects_headline(self) -> None:
        with pytest.raises(ValueError):
            consent.ConsentPartner(
                name="Scientists announce breakthrough in climate research",
                purpose="Analytics",
                data_collected=[],
            )


class TestConsentDetailsEmpty:
    """Tests for ConsentDetails.empty() factory."""

    def test_empty_defaults(self) -> None:
        result = consent.ConsentDetails.empty()
        assert result.has_manage_options is False
        assert result.categories == []
        assert result.partners == []
        assert result.purposes == []
        assert result.raw_text == ""

    def test_empty_with_raw_text(self) -> None:
        result = consent.ConsentDetails.empty(raw_text="some text")
        assert result.raw_text == "some text"

    def test_empty_with_partner_count(self) -> None:
        result = consent.ConsentDetails.empty(claimed_partner_count=42)
        assert result.claimed_partner_count == 42


class TestCookieConsentDetection:
    """Tests for CookieConsentDetection factory methods."""

    def test_not_found(self) -> None:
        result = consent.CookieConsentDetection.not_found("no banner")
        assert result.found is False
        assert result.error is False
        assert result.reason == "no banner"
        assert result.confidence == "low"

    def test_failed(self) -> None:
        result = consent.CookieConsentDetection.failed("timeout")
        assert result.found is False
        assert result.error is True
        assert result.reason == "timeout"

    def test_found_detection(self) -> None:
        result = consent.CookieConsentDetection(
            found=True,
            overlay_type="cookie-consent",
            selector=".accept-btn",
            button_text="Accept All",
            confidence="high",
            reason="Cookie banner detected",
        )
        assert result.found is True
        assert result.overlay_type == "cookie-consent"


class TestTrackingAnalysisResult:
    """Tests for TrackingAnalysisResult.to_text()."""

    def test_to_text_format(self) -> None:
        result = analysis.TrackingAnalysisResult(
            risk_level="high",
            risk_summary="Extensive tracking detected.",
            sections=[
                analysis.TrackingAnalysisSection(
                    heading="Tracking Technologies",
                    content="Multiple trackers found.",
                ),
                analysis.TrackingAnalysisSection(
                    heading="Data Collection",
                    content="Cookies and localStorage used.",
                ),
            ],
        )
        text = result.to_text()
        assert "Risk Level: high" in text
        assert "## Tracking Technologies" in text
        assert "Multiple trackers found" in text
        assert "## Data Collection" in text

    def test_to_text_empty_sections(self) -> None:
        result = analysis.TrackingAnalysisResult(
            risk_level="low",
            risk_summary="Minimal tracking.",
        )
        text = result.to_text()
        assert "Risk Level: low" in text
        assert "Minimal tracking" in text


class TestScoreBreakdown:
    """Tests for ScoreBreakdown model."""

    def test_default_values(self) -> None:
        sb = analysis.ScoreBreakdown()
        assert sb.total_score == 0
        assert sb.categories == {}
        assert sb.factors == []
        assert sb.summary == ""

    def test_with_categories(self) -> None:
        sb = analysis.ScoreBreakdown(
            total_score=75,
            categories={
                "cookies": analysis.CategoryScore(points=10, max_points=22),
                "thirdParty": analysis.CategoryScore(points=20, max_points=48),
            },
            factors=["Many third-party trackers"],
            summary="High tracking activity",
        )
        assert sb.total_score == 75
        assert "cookies" in sb.categories
        assert sb.categories["cookies"].points == 10

    def test_camel_case_serialization(self) -> None:
        sb = analysis.ScoreBreakdown(total_score=50)
        dumped = sb.model_dump(by_alias=True)
        assert "totalScore" in dumped


class TestPreConsentStats:
    """Tests for PreConsentStats model."""

    def test_defaults(self) -> None:
        stats = analysis.PreConsentStats()
        assert stats.total_cookies == 0
        assert stats.tracking_cookies == 0

    def test_with_values(self) -> None:
        stats = analysis.PreConsentStats(
            total_cookies=50,
            tracking_cookies=10,
            total_scripts=100,
            tracking_scripts=5,
        )
        assert stats.total_cookies == 50
        assert stats.tracking_cookies == 10


class TestTrackingSummary:
    """Tests for TrackingSummary model."""

    def test_creation(self) -> None:
        summary = analysis.TrackingSummary(
            analyzed_url="https://example.com",
            total_cookies=10,
            total_scripts=5,
            total_network_requests=100,
            local_storage_items=3,
            session_storage_items=1,
            third_party_domains=["tracker.com"],
            domain_breakdown=[],
            local_storage=[],
            session_storage=[],
        )
        assert summary.analyzed_url == "https://example.com"
        assert len(summary.third_party_domains) == 1


class TestConsentPlatformProfile:
    """Tests for ConsentPlatformProfile model."""

    def test_creation(self) -> None:
        data = {
            "name": "OneTrust",
            "vendor": "OneTrust LLC",
            "privacy_url": "https://onetrust.com/privacy",
            "tcf_registered": True,
            "cmp_id": 28,
            "container_selectors": ["#onetrust-consent-sdk"],
            "cookie_indicators": ["OptanonConsent"],
            "accept_button_patterns": ["#onetrust-accept-btn-handler"],
        }
        profile = consent.ConsentPlatformProfile("onetrust", data)
        assert profile.name == "OneTrust"
        assert profile.key == "onetrust"
        assert profile.tcf_registered is True
        assert profile.cmp_id == 28
        assert len(profile.container_selectors) == 1

    def test_defaults(self) -> None:
        profile = consent.ConsentPlatformProfile("test", {})
        assert profile.name == "test"
        assert profile.vendor == ""
        assert profile.tcf_registered is False
        assert profile.cmp_id is None
        assert profile.iframe_patterns == []
