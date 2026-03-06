"""Tests for src.agents.context_builder — pure helper functions."""

from __future__ import annotations

from src.agents.context_builder import (
    _build_consent_delta_lines,
    _build_consent_lines,
    _build_decoded_cookies_lines,
    _build_pre_consent_lines,
    _build_score_lines,
    _build_social_platforms_lines,
    _build_tc_string_lines,
    _format_partner,
    build_analysis_context,
    build_section_context,
)
from src.models import analysis, consent
from src.models.report import TrackerEntry


class TestBuildPreConsentLines:
    """Tests for _build_pre_consent_lines()."""

    def test_produces_markdown(self) -> None:
        stats = analysis.PreConsentStats(
            total_cookies=10,
            total_scripts=5,
            total_requests=50,
            tracking_cookies=3,
            tracking_scripts=2,
            tracker_requests=10,
        )
        lines = _build_pre_consent_lines(stats)
        text = "\n".join(lines)
        assert "Initial Page Load" in text
        assert "10" in text
        assert "3 matched tracking" in text

    def test_zero_stats(self) -> None:
        stats = analysis.PreConsentStats()
        lines = _build_pre_consent_lines(stats)
        assert len(lines) > 0


class TestBuildConsentDeltaLines:
    """Tests for _build_consent_delta_lines()."""

    def test_positive_delta(self) -> None:
        pre = analysis.PreConsentStats(total_cookies=5, total_scripts=10, total_requests=50)
        summary = analysis.TrackingSummary(
            analyzed_url="https://example.com",
            total_cookies=15,
            total_scripts=20,
            total_network_requests=100,
            local_storage_items=0,
            session_storage_items=0,
            third_party_domains=[],
            domain_breakdown=[],
            local_storage=[],
            session_storage=[],
        )
        lines = _build_consent_delta_lines(pre, summary)
        text = "\n".join(lines)
        assert "Post-Consent" in text
        assert "10" in text  # 15 - 5 = 10 new cookies

    def test_no_delta(self) -> None:
        pre = analysis.PreConsentStats(total_cookies=10, total_scripts=10, total_requests=100)
        summary = analysis.TrackingSummary(
            analyzed_url="https://example.com",
            total_cookies=10,
            total_scripts=10,
            total_network_requests=100,
            local_storage_items=0,
            session_storage_items=0,
            third_party_domains=[],
            domain_breakdown=[],
            local_storage=[],
            session_storage=[],
        )
        lines = _build_consent_delta_lines(pre, summary)
        assert lines == []


class TestBuildTcStringLines:
    """Tests for _build_tc_string_lines()."""

    def test_with_tc_data(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="",
            tc_string_data={
                "cmpId": 28,
                "cmpVersion": 5,
                "tcfPolicyVersion": 4,
                "purposeConsents": [1, 2, 3],
                "purposeLegitimateInterests": [7, 8],
                "specialFeatureOptIns": [],
                "vendorConsentCount": 120,
                "vendorLiCount": 50,
            },
        )
        lines = _build_tc_string_lines(cd)
        text = "\n".join(lines)
        assert "TC String" in text
        assert "CMP ID: 28" in text

    def test_with_ac_data(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="",
            ac_string_data={"vendorCount": 50},
        )
        lines = _build_tc_string_lines(cd)
        text = "\n".join(lines)
        assert "AC String" in text

    def test_with_validation(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="",
            tc_string_data={"cmpId": 1},
            tc_validation={
                "findings": [
                    {"severity": "high", "message": "Undisclosed purposes"},
                ]
            },
        )
        lines = _build_tc_string_lines(cd)
        text = "\n".join(lines)
        assert "Validation" in text
        assert "Undisclosed" in text

    def test_no_tc_data(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=False,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="",
        )
        lines = _build_tc_string_lines(cd)
        assert lines == []

    def test_with_resolved_vendors(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="",
            tc_string_data={
                "cmpId": 1,
                "resolvedVendorConsents": [
                    {"name": "Google"},
                    {"name": "Facebook"},
                ],
                "unresolvedVendorConsentCount": 5,
            },
        )
        lines = _build_tc_string_lines(cd)
        text = "\n".join(lines)
        assert "Google" in text
        assert "Unresolved" in text


class TestBuildSocialPlatformsLines:
    """Tests for _build_social_platforms_lines()."""

    def test_with_trackers(self) -> None:
        trackers = [
            TrackerEntry(
                name="Facebook",
                domains=["facebook.com", "connect.facebook.net"],
                cookies=["_fbp"],
                purpose="Social media tracking",
            ),
        ]
        lines = _build_social_platforms_lines(trackers)
        text = "\n".join(lines)
        assert "Facebook" in text
        assert "Social Media" in text

    def test_empty_trackers(self) -> None:
        lines = _build_social_platforms_lines([])
        assert lines == []


class TestBuildDecodedCookiesLines:
    """Tests for _build_decoded_cookies_lines()."""

    def test_with_decoded_data(self) -> None:
        decoded: dict[str, object] = {
            "USP String": {"version": 1, "notice": "Y", "optOut": "N"},
            "GA Client IDs": [{"id": "GA1.2.123"}],
        }
        lines = _build_decoded_cookies_lines(decoded)
        text = "\n".join(lines)
        assert "USP String" in text
        assert "GA Client IDs" in text

    def test_empty_decoded(self) -> None:
        lines = _build_decoded_cookies_lines({})
        assert lines == []

    def test_scalar_value(self) -> None:
        decoded: dict[str, object] = {"simple": "value"}
        lines = _build_decoded_cookies_lines(decoded)
        assert len(lines) > 0


class TestBuildConsentLines:
    """Tests for _build_consent_lines()."""

    def test_with_categories_and_partners(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[
                consent.ConsentCategory(name="Analytics", description="Usage data", required=False),
            ],
            partners=[
                consent.ConsentPartner(name="Google", purpose="Analytics", data_collected=["pageviews"]),
            ],
            purposes=["Analytics"],
            raw_text="We use cookies.",
            claimed_partner_count=42,
        )
        lines = _build_consent_lines(cd, include_raw_text=False, include_partner_urls=False)
        text = "\n".join(lines)
        assert "Analytics" in text
        assert "Google" in text
        assert "42" in text

    def test_with_raw_text(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=False,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="Raw consent text here.",
        )
        lines = _build_consent_lines(cd, include_raw_text=True, include_partner_urls=False)
        text = "\n".join(lines)
        assert "Raw consent text here" in text

    def test_empty_consent(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=False,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="",
        )
        lines = _build_consent_lines(cd, include_raw_text=False, include_partner_urls=False)
        text = "\n".join(lines)
        assert "None disclosed" in text or "None listed" in text


class TestFormatPartner:
    """Tests for _format_partner()."""

    def test_basic_partner(self) -> None:
        p = consent.ConsentPartner(name="Google", purpose="Analytics", data_collected=[])
        result = _format_partner(p, include_url=False)
        assert "Google" in result
        assert "Analytics" in result

    def test_partner_with_risk(self) -> None:
        p = consent.ConsentPartner(
            name="DataBroker",
            purpose="Data brokering",
            data_collected=["browsing"],
            risk_level="critical",
            risk_category="data-broker",
            concerns=["Sells personal data"],
        )
        result = _format_partner(p, include_url=False)
        assert "CRITICAL RISK" in result
        assert "data-broker" in result
        assert "Sells personal data" in result

    def test_partner_with_url(self) -> None:
        p = consent.ConsentPartner(
            name="Google",
            purpose="Analytics",
            data_collected=[],
            url="https://google.com",
        )
        result = _format_partner(p, include_url=True)
        assert "https://google.com" in result

    def test_partner_url_excluded(self) -> None:
        p = consent.ConsentPartner(
            name="Google",
            purpose="Analytics",
            data_collected=[],
            url="https://google.com",
        )
        result = _format_partner(p, include_url=False)
        assert "https://google.com" not in result


class TestBuildScoreLines:
    """Tests for _build_score_lines()."""

    def test_with_categories(self) -> None:
        sb = analysis.ScoreBreakdown(
            total_score=75,
            factors=["Many cookies", "Third-party trackers"],
            categories={
                "cookies": analysis.CategoryScore(points=10, max_points=22, issues=["20 cookies"]),
                "thirdParty": analysis.CategoryScore(points=20, max_points=48, issues=["many"]),
            },
        )
        lines = _build_score_lines(sb)
        text = "\n".join(lines)
        assert "75/100" in text
        assert "cookies: 10/22" in text
        assert "Many cookies" in text

    def test_low_score(self) -> None:
        sb = analysis.ScoreBreakdown(total_score=15)
        lines = _build_score_lines(sb)
        text = "\n".join(lines)
        assert "15/100" in text
        assert "Low" in text


# ── High-level context builders ────────────────────────────────


def _make_tracking_summary(
    *,
    total_cookies: int = 10,
    total_scripts: int = 5,
    total_network_requests: int = 100,
) -> analysis.TrackingSummary:
    return analysis.TrackingSummary(
        analyzed_url="https://example.com",
        total_cookies=total_cookies,
        total_scripts=total_scripts,
        total_network_requests=total_network_requests,
        local_storage_items=3,
        session_storage_items=1,
        third_party_domains=["tracker.com", "ads.net"],
        domain_breakdown=[
            analysis.DomainBreakdown(
                domain="tracker.com",
                cookie_count=3,
                cookie_names=["_ga", "_gid", "_gat"],
                script_count=1,
                request_count=10,
                request_types=["xhr"],
            ),
        ],
        local_storage=[{"key": "k", "value": "v"}],
        session_storage=[],
    )


class TestBuildAnalysisContext:
    """Tests for build_analysis_context()."""

    def test_basic_context(self) -> None:
        summary = _make_tracking_summary()
        result = build_analysis_context(summary)
        assert "example.com" in result
        assert "10" in result
        assert "Third-Party" in result

    def test_with_consent(self) -> None:
        summary = _make_tracking_summary()
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[consent.ConsentCategory(name="Analytics", description="Usage", required=False)],
            partners=[],
            purposes=["Analytics"],
            raw_text="We use cookies",
            claimed_partner_count=42,
        )
        result = build_analysis_context(summary, consent_details=cd)
        assert "Consent Dialog" in result
        assert "Analytics" in result

    def test_with_pre_consent_stats(self) -> None:
        summary = _make_tracking_summary(total_cookies=20)
        pre = analysis.PreConsentStats(total_cookies=5, total_scripts=3, total_requests=50)
        result = build_analysis_context(summary, pre_consent_stats=pre)
        assert "Post-Consent" in result

    def test_with_score(self) -> None:
        summary = _make_tracking_summary()
        sb = analysis.ScoreBreakdown(total_score=75, factors=["Heavy tracking"])
        result = build_analysis_context(summary, score_breakdown=sb)
        assert "75/100" in result

    def test_with_decoded_cookies(self) -> None:
        summary = _make_tracking_summary()
        decoded: dict[str, object] = {"uspString": {"rawString": "1YNN"}}
        result = build_analysis_context(summary, decoded_cookies=decoded)
        assert "USP" in result or "Privacy Cookie" in result


class TestBuildSectionContext:
    """Tests for build_section_context()."""

    def test_known_section(self) -> None:
        summary = _make_tracking_summary()
        result = build_section_context("cookie-analysis", summary)
        assert len(result) > 0
        assert "example.com" in result

    def test_unknown_section_falls_back(self) -> None:
        summary = _make_tracking_summary()
        result = build_section_context("nonexistent-section", summary)
        assert "example.com" in result
        assert "Third-Party" in result

    def test_section_with_consent(self) -> None:
        summary = _make_tracking_summary()
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[consent.ConsentCategory(name="Analytics", description="Usage", required=False)],
            partners=[],
            purposes=[],
            raw_text="",
            claimed_partner_count=10,
        )
        result = build_section_context("consent-analysis", summary, consent_details=cd)
        assert len(result) > 0

    def test_section_with_score(self) -> None:
        summary = _make_tracking_summary()
        sb = analysis.ScoreBreakdown(total_score=50, factors=["Moderate"])
        result = build_section_context("privacy-risk", summary, score_breakdown=sb)
        assert "50/100" in result

    def test_section_with_social_trackers(self) -> None:
        summary = _make_tracking_summary()
        trackers = [
            TrackerEntry(name="Facebook", domains=["facebook.com"], purpose="Social"),
        ]
        result = build_section_context(
            "social-media-implications",
            summary,
            social_media_trackers=trackers,
        )
        assert "Facebook" in result

    def test_section_with_pre_consent(self) -> None:
        summary = _make_tracking_summary()
        pre = analysis.PreConsentStats(total_cookies=5, tracking_cookies=2)
        result = build_section_context(
            "tracking-technologies",
            summary,
            pre_consent_stats=pre,
        )
        assert len(result) > 0
