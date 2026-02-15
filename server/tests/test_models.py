"""Tests for Pydantic models in src.models."""

from __future__ import annotations

import pytest

from src.models import analysis, browser, consent, partners, report, tracking_data

# ── Tracking Data Models ────────────────────────────────────────


class TestTrackedCookie:
    """Tests for TrackedCookie."""

    def test_create(self, sample_cookie: tracking_data.TrackedCookie) -> None:
        assert sample_cookie.name == "session_id"
        assert sample_cookie.domain == "example.com"

    def test_roundtrip_serialization(self, sample_cookie: tracking_data.TrackedCookie) -> None:
        data = sample_cookie.model_dump()
        restored = tracking_data.TrackedCookie.model_validate(data)
        assert restored == sample_cookie


class TestTrackedScript:
    """Tests for TrackedScript."""

    def test_defaults(self) -> None:
        script = tracking_data.TrackedScript(url="https://example.com/app.js", domain="example.com")
        assert script.timestamp == ""
        assert script.description is None
        assert script.resource_type == "script"
        assert script.group_id is None
        assert script.is_grouped is None


class TestScriptGroup:
    """Tests for ScriptGroup."""

    def test_create(self) -> None:
        group = tracking_data.ScriptGroup(
            id="example.com-app-chunks",
            name="App chunks",
            description="Code-split bundles",
            count=5,
            example_urls=["https://example.com/chunk1.js"],
            domain="example.com",
        )
        assert group.count == 5


class TestNetworkRequest:
    """Tests for NetworkRequest."""

    def test_defaults(self) -> None:
        req = tracking_data.NetworkRequest(
            url="https://example.com/api",
            domain="example.com",
            method="GET",
            resource_type="xhr",
            is_third_party=False,
            timestamp="2026-01-01T00:00:00Z",
        )
        assert req.status_code is None
        assert req.post_data is None
        assert req.pre_consent is False


class TestStorageItem:
    """Tests for StorageItem."""

    def test_create(self, sample_storage_item: tracking_data.StorageItem) -> None:
        assert sample_storage_item.key == "theme"
        assert sample_storage_item.value == "dark"


# ── Consent Models ──────────────────────────────────────────────


class TestCookieConsentDetection:
    """Tests for CookieConsentDetection."""

    def test_not_found_factory(self) -> None:
        detection = consent.CookieConsentDetection.not_found("No overlay visible")
        assert detection.found is False
        assert detection.overlay_type is None
        assert detection.button_text is None
        assert detection.confidence == "low"
        assert detection.reason == "No overlay visible"

    def test_found_detection(self) -> None:
        detection = consent.CookieConsentDetection(
            found=True,
            overlay_type="cookie-consent",
            selector="#accept-btn",
            button_text="Accept All",
            confidence="high",
            reason="Consent banner detected",
        )
        assert detection.found is True
        assert detection.overlay_type == "cookie-consent"


class TestConsentDetails:
    """Tests for ConsentDetails."""

    def test_empty_factory(self) -> None:
        details = consent.ConsentDetails.empty()
        assert details.has_manage_options is False
        assert details.categories == []
        assert details.partners == []
        assert details.purposes == []
        assert details.raw_text == ""
        assert details.claimed_partner_count is None

    def test_empty_with_raw_text(self) -> None:
        details = consent.ConsentDetails.empty(raw_text="Sample text", claimed_partner_count=10)
        assert details.raw_text == "Sample text"
        assert details.claimed_partner_count == 10

    def test_camel_case_serialization(self, sample_consent_details: consent.ConsentDetails) -> None:
        data = sample_consent_details.model_dump(by_alias=True)
        assert "hasManageOptions" in data
        assert "claimedPartnerCount" in data
        assert "rawText" in data

    def test_snake_case_fields_still_work(self, sample_consent_details: consent.ConsentDetails) -> None:
        data = sample_consent_details.model_dump()
        assert "has_manage_options" in data


class TestConsentPartner:
    """Tests for ConsentPartner."""

    def test_camel_case_aliases(self) -> None:
        partner = consent.ConsentPartner(
            name="Google",
            purpose="Analytics",
            data_collected=["browsing"],
            risk_level="high",
            risk_score=7,
        )
        data = partner.model_dump(by_alias=True)
        assert "dataCollected" in data
        assert "riskLevel" in data
        assert "riskScore" in data

    def test_optional_fields_default_none(self) -> None:
        partner = consent.ConsentPartner(
            name="Test",
            purpose="Testing",
            data_collected=[],
        )
        assert partner.risk_level is None
        assert partner.risk_category is None
        assert partner.risk_score is None
        assert partner.concerns is None


# ── Analysis Models ─────────────────────────────────────────────


class TestPreConsentStats:
    """Tests for PreConsentStats."""

    def test_defaults(self) -> None:
        stats = analysis.PreConsentStats()
        assert stats.total_cookies == 0
        assert stats.tracking_cookies == 0

    def test_populated(self, sample_pre_consent_stats: analysis.PreConsentStats) -> None:
        assert sample_pre_consent_stats.tracking_cookies == 3
        assert sample_pre_consent_stats.tracking_scripts == 5


class TestScoreBreakdown:
    """Tests for ScoreBreakdown."""

    def test_defaults(self) -> None:
        sb = analysis.ScoreBreakdown()
        assert sb.total_score == 0
        assert sb.categories == {}
        assert sb.factors == []

    def test_with_categories(self) -> None:
        sb = analysis.ScoreBreakdown(
            total_score=72,
            categories={
                "cookies": analysis.CategoryScore(points=8, max_points=15, issues=["Too many cookies"]),
            },
        )
        assert sb.categories["cookies"].points == 8

    def test_camel_case_serialization(self) -> None:
        sb = analysis.ScoreBreakdown(total_score=50)
        data = sb.model_dump(by_alias=True)
        assert "totalScore" in data


class TestSummaryFinding:
    """Tests for SummaryFinding."""

    def test_create(self) -> None:
        finding = analysis.SummaryFinding(type="critical", text="Excessive tracking detected")
        assert finding.type == "critical"
        assert finding.text == "Excessive tracking detected"

    @pytest.mark.parametrize("finding_type", ["critical", "high", "moderate", "info", "positive"])
    def test_valid_types(self, finding_type: str) -> None:
        finding = analysis.SummaryFinding(type=finding_type, text="Test")
        assert finding.type == finding_type


class TestTrackingSummary:
    """Tests for TrackingSummary."""

    def test_create(self) -> None:
        summary = analysis.TrackingSummary(
            analyzed_url="https://example.com",
            total_cookies=5,
            total_scripts=10,
            total_network_requests=50,
            local_storage_items=3,
            session_storage_items=1,
            third_party_domains=["tracker.com"],
            domain_breakdown=[],
            local_storage=[],
            session_storage=[],
        )
        assert summary.total_cookies == 5


# ── Browser Models ──────────────────────────────────────────────


class TestNavigationResult:
    """Tests for NavigationResult."""

    def test_success(self) -> None:
        result = browser.NavigationResult(
            success=True,
            status_code=200,
            status_text="OK",
            is_access_denied=False,
            error_message=None,
        )
        assert result.success is True
        assert result.status_code == 200

    def test_failure(self) -> None:
        result = browser.NavigationResult(
            success=False,
            status_code=403,
            status_text="Forbidden",
            is_access_denied=True,
            error_message="Access denied",
        )
        assert result.is_access_denied is True


class TestDeviceConfig:
    """Tests for DeviceConfig."""

    def test_mobile_device(self) -> None:
        config = browser.DeviceConfig(
            user_agent="Mozilla/5.0 (iPhone...)",
            viewport=browser.ViewportSize(width=430, height=932),
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
        )
        assert config.is_mobile is True
        assert config.viewport.width == 430


# ── Partner Models ──────────────────────────────────────────────


class TestPartnerClassification:
    """Tests for PartnerClassification."""

    def test_create(self) -> None:
        classification = partners.PartnerClassification(
            name="Google",
            risk_level="high",
            category="advertising",
            reason="Major ad network",
            concerns=["Cross-site tracking"],
            risk_score=7,
        )
        assert classification.risk_score == 7
        assert classification.category == "advertising"


class TestPartnerRiskSummary:
    """Tests for PartnerRiskSummary."""

    def test_create(self) -> None:
        summary = partners.PartnerRiskSummary(
            critical_count=2,
            high_count=5,
            total_risk_score=42,
            worst_partners=["DataBroker Inc"],
        )
        assert summary.critical_count == 2


# ── Report Models ───────────────────────────────────────────────


class TestStructuredReport:
    """Tests for StructuredReport."""

    def test_defaults(self) -> None:
        report_obj = report.StructuredReport()
        assert report_obj.tracking_technologies.analytics == []
        assert report_obj.cookie_analysis.total == 0
        assert report_obj.consent_analysis.has_consent_dialog is False

    def test_camel_case_serialization(self) -> None:
        report_obj = report.StructuredReport()
        data = report_obj.model_dump(by_alias=True)
        assert "trackingTechnologies" in data
        assert "dataCollection" in data
        assert "privacyRisk" in data
        assert "cookieAnalysis" in data
        assert "storageAnalysis" in data
        assert "consentAnalysis" in data
        assert "keyVendors" in data
        assert "recommendations" in data

    def test_nested_model(self) -> None:
        tracker = report.TrackerEntry(
            name="Google Analytics",
            domains=["google-analytics.com"],
            cookies=["_ga", "_gid"],
            purpose="Web analytics",
        )
        assert tracker.name == "Google Analytics"
        data = tracker.model_dump(by_alias=True)
        assert "storageKeys" in data
