"""Tests for analysis_pipeline render helpers — pure functions.

These _render_* functions take Pydantic models and return
lists of strings.  No async, no browser, no LLM.
"""

from __future__ import annotations

from src.analysis.scripts import ScriptAnalysisResult
from src.models import analysis, consent
from src.models import report as report_models
from src.pipeline.analysis_pipeline import (
    _build_complete_payload,
    _build_scripts_payload,
    _build_tracking_payload,
    _render_ac_string_data,
    _render_consent_analysis,
    _render_cookie_analysis,
    _render_data_collection,
    _render_decoded_cookies,
    _render_header,
    _render_llm_usage,
    _render_pre_consent_stats,
    _render_privacy_risk,
    _render_recommendations,
    _render_report_text,
    _render_score_breakdown,
    _render_storage_analysis,
    _render_summary_findings,
    _render_tc_string_data,
    _render_tc_validation,
    _render_third_party_services,
    _render_tracking_technologies,
)

# ── Helpers ─────────────────────────────────────────────────────


def _empty_report() -> report_models.StructuredReport:
    return report_models.StructuredReport()


def _populated_report() -> report_models.StructuredReport:
    return report_models.StructuredReport(
        tracking_technologies=report_models.TrackingTechnologiesSection(
            analytics=[
                report_models.TrackerEntry(
                    name="Google Analytics",
                    domains=["google-analytics.com"],
                    purpose="Web analytics",
                ),
            ],
            advertising=[
                report_models.TrackerEntry(
                    name="DoubleClick",
                    domains=["doubleclick.net"],
                    purpose="Ad serving",
                ),
            ],
        ),
        data_collection=report_models.DataCollectionSection(
            items=[
                report_models.DataCollectionItem(
                    category="Browsing Behaviour",
                    details=["Page views", "Click tracking"],
                    risk="medium",
                    shared_with=["Google"],  # type: ignore[list-item]
                ),
            ],
        ),
        third_party_services=report_models.ThirdPartySection(
            total_domains=5,
            groups=[
                report_models.ThirdPartyGroup(
                    category="Analytics",
                    services=["Google Analytics"],  # type: ignore[list-item]
                    privacy_impact="Medium",
                ),
            ],
            summary="Multiple third-party services detected.",
        ),
        privacy_risk=report_models.PrivacyRiskSection(
            overall_risk="high",
            factors=[
                report_models.RiskFactor(description="Excessive tracking", severity="high"),
            ],
            summary="High risk due to extensive tracking.",
        ),
        cookie_analysis=report_models.CookieAnalysisSection(
            total=15,
            groups=[
                report_models.CookieGroup(
                    category="Analytics",
                    cookies=["_ga", "_gid"],
                    concern_level="medium",
                ),
            ],
            concerning_cookies=["IDE (DoubleClick)"],
        ),
        storage_analysis=report_models.StorageAnalysisSection(
            local_storage_count=5,
            session_storage_count=2,
            local_storage_concerns=["Tracking IDs in localStorage"],
            session_storage_concerns=["Session replay data"],
            summary="Storage used for tracking.",
        ),
        consent_analysis=report_models.ConsentAnalysisSection(
            has_consent_dialog=True,
            categories_disclosed=4,
            partners_disclosed=42,
            discrepancies=[
                report_models.ConsentDiscrepancy(
                    claimed="42 partners",
                    actual="67 third-party domains",
                    severity="high",
                ),
            ],
            summary="Consent dialog present but discrepancies found.",
            consent_platform="OneTrust",
            consent_platform_url="https://onetrust.com",
        ),
        recommendations=report_models.RecommendationsSection(
            groups=[
                report_models.RecommendationGroup(
                    category="Cookies",
                    items=["Consider reducing cookie count"],
                ),
            ],
        ),
    )


# ── Render function tests ──────────────────────────────────────


class TestRenderHeader:
    def test_contains_url(self) -> None:
        lines = _render_header("https://example.com", 75, "High risk")
        text = "\n".join(lines)
        assert "example.com" in text
        assert "75/100" in text
        assert "High risk" in text

    def test_contains_timestamp(self) -> None:
        lines = _render_header("https://example.com", 50, "")
        text = "\n".join(lines)
        assert "UTC" in text


class TestRenderScoreBreakdown:
    def test_none_returns_empty(self) -> None:
        assert _render_score_breakdown(None) == []

    def test_empty_categories_returns_empty(self) -> None:
        sb = analysis.ScoreBreakdown(total_score=50)
        assert _render_score_breakdown(sb) == []

    def test_with_categories(self) -> None:
        sb = analysis.ScoreBreakdown(
            total_score=75,
            categories={
                "cookies": analysis.CategoryScore(points=10, max_points=22, issues=["Too many"]),
            },
            factors=["Excessive tracking"],
        )
        lines = _render_score_breakdown(sb)
        text = "\n".join(lines)
        assert "cookies: 10/22" in text
        assert "Too many" in text
        assert "Excessive tracking" in text


class TestRenderPreConsentStats:
    def test_none_returns_empty(self) -> None:
        assert _render_pre_consent_stats(None) == []

    def test_with_stats(self) -> None:
        stats = analysis.PreConsentStats(
            total_cookies=10,
            tracking_cookies=3,
            total_scripts=20,
            tracking_scripts=5,
            total_requests=100,
            tracker_requests=12,
            total_local_storage=4,
            total_session_storage=1,
        )
        lines = _render_pre_consent_stats(stats)
        text = "\n".join(lines)
        assert "10" in text
        assert "tracking: 3" in text


class TestRenderSummaryFindings:
    def test_empty_returns_empty(self) -> None:
        assert _render_summary_findings([]) == []

    def test_with_findings(self) -> None:
        findings = [
            analysis.SummaryFinding(type="critical", text="Too many trackers"),
            analysis.SummaryFinding(type="positive", text="HTTPS used"),
        ]
        lines = _render_summary_findings(findings)
        text = "\n".join(lines)
        assert "[CRITICAL]" in text
        assert "[POSITIVE]" in text
        assert "Too many trackers" in text


class TestRenderPrivacyRisk:
    def test_empty_summary_returns_empty(self) -> None:
        report = _empty_report()
        assert _render_privacy_risk(report) == []

    def test_with_risk(self) -> None:
        report = _populated_report()
        lines = _render_privacy_risk(report)
        text = "\n".join(lines)
        assert "HIGH" in text
        assert "Excessive tracking" in text


class TestRenderTrackingTechnologies:
    def test_empty_returns_empty(self) -> None:
        assert _render_tracking_technologies(_empty_report()) == []

    def test_with_trackers(self) -> None:
        report = _populated_report()
        lines = _render_tracking_technologies(report)
        text = "\n".join(lines)
        assert "Google Analytics" in text
        assert "DoubleClick" in text
        assert "Analytics:" in text
        assert "Advertising:" in text


class TestRenderDataCollection:
    def test_empty_returns_empty(self) -> None:
        assert _render_data_collection(_empty_report()) == []

    def test_with_items(self) -> None:
        report = _populated_report()
        lines = _render_data_collection(report)
        text = "\n".join(lines)
        assert "Browsing Behaviour" in text
        assert "Page views" in text
        assert "Google" in text


class TestRenderThirdPartyServices:
    def test_empty_returns_empty(self) -> None:
        assert _render_third_party_services(_empty_report()) == []

    def test_with_groups(self) -> None:
        report = _populated_report()
        lines = _render_third_party_services(report)
        text = "\n".join(lines)
        assert "5 domains" in text
        assert "Analytics" in text


class TestRenderCookieAnalysis:
    def test_empty_returns_empty(self) -> None:
        assert _render_cookie_analysis(_empty_report()) == []

    def test_with_cookies(self) -> None:
        report = _populated_report()
        lines = _render_cookie_analysis(report)
        text = "\n".join(lines)
        assert "15 cookies" in text
        assert "_ga" in text
        assert "IDE" in text


class TestRenderStorageAnalysis:
    def test_empty_returns_empty(self) -> None:
        assert _render_storage_analysis(_empty_report()) == []

    def test_with_storage(self) -> None:
        report = _populated_report()
        lines = _render_storage_analysis(report)
        text = "\n".join(lines)
        assert "localStorage: 5" in text
        assert "Tracking IDs" in text


class TestRenderConsentAnalysis:
    def test_empty_returns_empty(self) -> None:
        assert _render_consent_analysis(_empty_report(), None) == []

    def test_with_consent(self) -> None:
        report = _populated_report()
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[
                consent.ConsentCategory(name="Analytics", description="Usage data", required=False),
            ],
            partners=[
                consent.ConsentPartner(name="Google", purpose="Analytics", data_collected=["pageviews"]),
            ],
            purposes=["Analytics"],
            raw_text="",
            claimed_partner_count=42,
        )
        lines = _render_consent_analysis(report, cd)
        text = "\n".join(lines)
        assert "Consent dialog: Yes" in text
        assert "OneTrust" in text
        assert "42 partners" in text


class TestRenderRecommendations:
    def test_empty_returns_empty(self) -> None:
        assert _render_recommendations(_empty_report()) == []

    def test_with_recommendations(self) -> None:
        report = _populated_report()
        lines = _render_recommendations(report)
        text = "\n".join(lines)
        assert "Cookies" in text
        assert "reducing cookie count" in text


class TestRenderTcStringData:
    def test_none_returns_empty(self) -> None:
        assert _render_tc_string_data(None) == []

    def test_no_tc_data_returns_empty(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=False,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="",
        )
        assert _render_tc_string_data(cd) == []

    def test_with_tc_data(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=False,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="",
            tc_string_data={
                "version": 2,
                "cmpId": 28,
                "cmpVersion": 5,
                "consentLanguage": "EN",
                "vendorListVersion": 100,
                "publisherCountryCode": "GB",
                "isServiceSpecific": True,
                "created": "2026-01-01",
                "lastUpdated": "2026-01-02",
                "purposeConsents": [1, 2, 3],
                "vendorConsentCount": 150,
                "vendorLiCount": 50,
            },
        )
        lines = _render_tc_string_data(cd)
        text = "\n".join(lines)
        assert "CMP ID:" in text
        assert "28" in text
        assert "150" in text


class TestRenderAcStringData:
    def test_none_returns_empty(self) -> None:
        assert _render_ac_string_data(None) == []

    def test_with_ac_data(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=False,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="",
            ac_string_data={
                "version": 2,
                "vendorCount": 80,
                "resolvedProviders": [
                    {"name": "Google", "id": 1},
                    {"name": "Facebook", "id": 2},
                ],
                "unresolvedProviderCount": 10,
            },
        )
        lines = _render_ac_string_data(cd)
        text = "\n".join(lines)
        assert "AC STRING" in text
        assert "80" in text
        assert "Google" in text


class TestRenderTcValidation:
    def test_none_returns_empty(self) -> None:
        assert _render_tc_validation(None) == []

    def test_with_findings(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=False,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="",
            tc_validation={
                "vendorConsentCount": 150,
                "vendorLiCount": 50,
                "claimedPartnerCount": 42,
                "vendorCountMismatch": True,
                "specialFeatures": ["Precise geolocation"],
                "findings": [
                    {"severity": "high", "title": "Undisclosed purposes", "detail": "Purpose 3 not disclosed"},
                ],
            },
        )
        lines = _render_tc_validation(cd)
        text = "\n".join(lines)
        assert "VALIDATION" in text
        assert "mismatch" in text
        assert "Undisclosed" in text


class TestRenderDecodedCookies:
    def test_none_returns_empty(self) -> None:
        assert _render_decoded_cookies(None) == []

    def test_empty_returns_empty(self) -> None:
        assert _render_decoded_cookies({}) == []

    def test_usp_string(self) -> None:
        decoded: dict[str, object] = {
            "uspString": {
                "rawString": "1YNN",
                "noticeLabel": "Yes",
                "optOutLabel": "No",
                "lspaLabel": "No",
            },
        }
        lines = _render_decoded_cookies(decoded)
        text = "\n".join(lines)
        assert "USP" in text
        assert "1YNN" in text

    def test_google_analytics(self) -> None:
        decoded: dict[str, object] = {
            "googleAnalytics": {
                "clientId": "123456.789",
                "firstVisit": "2026-01-01",
            },
        }
        lines = _render_decoded_cookies(decoded)
        text = "\n".join(lines)
        assert "Google Analytics" in text

    def test_facebook_pixel(self) -> None:
        decoded: dict[str, object] = {
            "facebookPixel": {
                "fbp": {"browserId": "abc123", "created": "2026-01-01"},
                "fbc": {"fbclid": "xyz789abcdef", "clicked": "2026-01-01"},
            },
        }
        lines = _render_decoded_cookies(decoded)
        text = "\n".join(lines)
        assert "Facebook" in text

    def test_google_ads(self) -> None:
        decoded: dict[str, object] = {
            "googleAds": {
                "gclAu": {"version": 1, "created": "2026-01-01"},
                "gclAw": {"gclid": "test123456", "clicked": "2026-01-01"},
            },
        }
        lines = _render_decoded_cookies(decoded)
        text = "\n".join(lines)
        assert "Google Ads" in text

    def test_onetrust(self) -> None:
        decoded: dict[str, object] = {
            "oneTrust": {
                "categories": [
                    {"id": "C0001", "name": "Necessary", "consented": True},
                    {"id": "C0002", "name": "Performance", "consented": False},
                ],
                "isGpcApplied": True,
            },
        }
        lines = _render_decoded_cookies(decoded)
        text = "\n".join(lines)
        assert "OneTrust" in text
        assert "GPC" in text

    def test_cookiebot(self) -> None:
        decoded: dict[str, object] = {
            "cookiebot": {
                "categories": [
                    {"name": "Necessary", "consented": True},
                    {"name": "Marketing", "consented": False},
                ],
            },
        }
        lines = _render_decoded_cookies(decoded)
        text = "\n".join(lines)
        assert "Cookiebot" in text

    def test_google_socs(self) -> None:
        decoded: dict[str, object] = {"googleSocs": {"consentMode": "accepted"}}
        lines = _render_decoded_cookies(decoded)
        text = "\n".join(lines)
        assert "SOCS" in text

    def test_gpp_string(self) -> None:
        decoded: dict[str, object] = {
            "gppString": {
                "rawString": "DBABLA~test",
                "segmentCount": 2,
                "sections": [{"name": "usnat", "id": 7}],
            },
        }
        lines = _render_decoded_cookies(decoded)
        text = "\n".join(lines)
        assert "GPP" in text


class TestRenderLlmUsage:
    def test_no_calls_returns_empty(self) -> None:
        from src.utils import usage_tracking

        usage_tracking.reset()
        assert _render_llm_usage() == []

    def test_with_calls(self) -> None:
        from src.utils import usage_tracking

        usage_tracking.reset()
        usage_tracking.record("TestAgent", input_tokens=100, output_tokens=50)
        lines = _render_llm_usage()
        text = "\n".join(lines)
        assert "LLM USAGE" in text
        assert "1" in text  # total calls
        usage_tracking.reset()


class TestRenderReportText:
    def test_full_report(self) -> None:
        report = _populated_report()
        sb = analysis.ScoreBreakdown(total_score=75, factors=["Heavy tracking"])
        text = _render_report_text(
            "https://example.com",
            75,
            "High tracking",
            [analysis.SummaryFinding(type="critical", text="Too many trackers")],
            report,
            score_breakdown=sb,
        )
        assert "example.com" in text
        assert "75/100" in text
        assert "TRACKING TECHNOLOGIES" in text

    def test_empty_report(self) -> None:
        report = _empty_report()
        text = _render_report_text(
            "https://example.com",
            20,
            "Low risk",
            [],
            report,
        )
        assert "example.com" in text
        assert "20/100" in text


# ── Payload builder tests ──────────────────────────────────────


class TestBuildTrackingPayload:
    def test_with_data(self) -> None:
        from src.models.tracking_data import CapturedStorage, NetworkRequest, StorageItem, TrackedCookie

        cookies = [
            TrackedCookie(
                name="_ga",
                value="v",
                domain="example.com",
                path="/",
                expires=0,
                http_only=False,
                secure=False,
                same_site="None",
                timestamp="t",
            )
        ]
        requests = [
            NetworkRequest(
                url="https://example.com/api",
                domain="example.com",
                method="GET",
                resource_type="xhr",
                is_third_party=False,
                timestamp="t",
            )
        ]
        storage = CapturedStorage(
            local_storage=[StorageItem(key="k", value="v", timestamp="t")],
        )
        event = _build_tracking_payload(
            final_cookies=cookies,
            final_requests=requests,
            storage=storage,
        )
        assert "completeTracking" in event

    def test_empty_data(self) -> None:
        event = _build_tracking_payload()
        assert "completeTracking" in event


class TestBuildScriptsPayload:
    def test_with_scripts(self) -> None:
        from src.models.tracking_data import ScriptGroup, TrackedScript

        result = ScriptAnalysisResult(
            scripts=[TrackedScript(url="https://example.com/app.js", domain="example.com")],
            groups=[
                ScriptGroup(
                    id="app-1",
                    name="App",
                    description="App bundle",
                    count=1,
                    example_urls=["https://example.com/app.js"],
                    domain="example.com",
                )
            ],
        )
        event = _build_scripts_payload(result)
        assert "completeScripts" in event


class TestBuildCompletePayload:
    def test_with_report(self) -> None:
        report = _populated_report()
        sb = analysis.ScoreBreakdown(total_score=65)
        event = _build_complete_payload(
            report,
            [analysis.SummaryFinding(type="info", text="Note")],
            sb,
            None,
        )
        assert '"complete"' in event or "complete" in event
