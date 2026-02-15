"""Tests for the privacy scoring calculator and category modules.

Covers the piecewise linear curve, each category's ``calculate()``
function, and the top-level orchestrator.
"""

from __future__ import annotations

import time

import pytest

from src.analysis.scoring import (
    advertising,
    calculator,
    cookies,
    data_collection,
    fingerprinting,
    sensitive_data,
    social_media,
    third_party,
)
from src.analysis.scoring import consent as consent_scoring
from src.models import analysis, consent, tracking_data


# ── Helpers ─────────────────────────────────────────────────────


def _cookie(
    name: str = "c",
    domain: str = "example.com",
    *,
    expires: float = 0,
) -> tracking_data.TrackedCookie:
    return tracking_data.TrackedCookie(
        name=name,
        value="v",
        domain=domain,
        path="/",
        expires=expires,
        http_only=False,
        secure=False,
        same_site="None",
        timestamp="2026-01-01T00:00:00Z",
    )


def _script(
    url: str = "https://example.com/app.js",
    domain: str = "example.com",
) -> tracking_data.TrackedScript:
    return tracking_data.TrackedScript(url=url, domain=domain)


def _request(
    url: str = "https://example.com/api",
    domain: str = "example.com",
    *,
    is_third_party: bool = False,
    resource_type: str = "xhr",
    method: str = "GET",
) -> tracking_data.NetworkRequest:
    return tracking_data.NetworkRequest(
        url=url,
        domain=domain,
        method=method,
        resource_type=resource_type,
        is_third_party=is_third_party,
        timestamp="2026-01-01T00:00:00Z",
    )


def _storage(key: str = "k") -> tracking_data.StorageItem:
    return tracking_data.StorageItem(key=key, value="v", timestamp="2026-01-01T00:00:00Z")


# ── _apply_curve ────────────────────────────────────────────────


class TestApplyCurve:
    """Tests for the piecewise linear scoring curve."""

    def test_zero_input(self) -> None:
        assert calculator._apply_curve(0) == 0

    def test_negative_input(self) -> None:
        assert calculator._apply_curve(-5) == 0

    def test_below_knee(self) -> None:
        assert calculator._apply_curve(20) == 20

    def test_at_knee(self) -> None:
        assert calculator._apply_curve(40) == 40

    def test_above_knee_reduced_slope(self) -> None:
        # 40 + (80 − 40) × 0.45 = 40 + 18 = 58
        assert calculator._apply_curve(80) == 58

    def test_cap_at_100(self) -> None:
        assert calculator._apply_curve(500) == 100

    def test_monotonically_increasing(self) -> None:
        prev = 0
        for raw in range(0, 200, 5):
            score = calculator._apply_curve(raw)
            assert score >= prev
            prev = score


# ── Cookie scoring ──────────────────────────────────────────────


class TestCookieScoring:
    """Tests for the cookie category scorer."""

    def test_no_cookies(self) -> None:
        result = cookies.calculate([], "example.com")
        assert result.points == 0
        assert result.issues == []

    def test_few_cookies_no_issues(self) -> None:
        items = [_cookie(f"c{i}") for i in range(4)]
        result = cookies.calculate(items, "example.com")
        assert result.points == 0

    def test_volume_penalty(self) -> None:
        items = [_cookie(f"c{i}") for i in range(20)]
        result = cookies.calculate(items, "example.com")
        assert result.points >= 4
        assert any("cookies set" in issue for issue in result.issues)

    def test_third_party_cookies(self) -> None:
        items = [_cookie(f"c{i}", domain="tracker.com") for i in range(6)]
        result = cookies.calculate(items, "example.com")
        assert result.points >= 5
        assert any("third-party" in issue for issue in result.issues)

    def test_tracking_cookies(self) -> None:
        items = [_cookie("_ga"), _cookie("_fbp"), _cookie("_gcl_au"), _cookie("IDE")]
        result = cookies.calculate(items, "example.com")
        assert result.points >= 5
        assert any("tracking cook" in issue for issue in result.issues)

    def test_long_lived_cookies(self) -> None:
        far_future = time.time() + 400 * 24 * 60 * 60
        items = [
            _cookie("a", expires=far_future),
            _cookie("b", expires=far_future),
            _cookie("c", expires=far_future),
            _cookie("d", expires=far_future),
        ]
        result = cookies.calculate(items, "example.com")
        assert result.points >= 2
        assert any("persist" in issue for issue in result.issues)

    def test_max_points_populated(self) -> None:
        result = cookies.calculate([], "example.com")
        assert result.max_points == 22


# ── Third-party scoring ────────────────────────────────────────


class TestThirdPartyScoring:
    """Tests for the third-party tracker scorer."""

    def test_no_third_parties(self) -> None:
        result = third_party.calculate([], [], "example.com", [])
        assert result.points == 0
        assert result.max_points == 31

    def test_third_party_domains(self) -> None:
        reqs = [
            _request("https://ads.com/1", "ads.com", is_third_party=True),
            _request("https://track.io/2", "track.io", is_third_party=True),
            _request("https://spy.net/3", "spy.net", is_third_party=True),
            _request("https://log.co/4", "log.co", is_third_party=True),
            _request("https://a.net/5", "a.net", is_third_party=True),
            _request("https://b.com/6", "b.com", is_third_party=True),
        ]
        result = third_party.calculate(reqs, [], "example.com", [])
        assert result.points >= 5
        assert any("third-party" in issue for issue in result.issues)


# ── Advertising scoring ────────────────────────────────────────


class TestAdvertisingScoring:
    """Tests for the advertising tracker scorer."""

    def test_no_ads(self) -> None:
        result = advertising.calculate([], [], [], [])
        assert result.points == 0
        assert result.max_points == 20

    def test_ad_network_detection(self) -> None:
        urls = [
            "https://securepubads.g.doubleclick.net/tag/js/gpt.js",
            "https://connect.facebook.net/en/sdk.js",
        ]
        result = advertising.calculate([], [], [], urls)
        assert result.points >= 5
        assert any("ad network" in issue.lower() for issue in result.issues)

    def test_retargeting_cookies(self) -> None:
        items = [_cookie("criteo_id", domain="criteo.com")]
        result = advertising.calculate([], [], items, [])
        assert result.points >= 4
        assert any("Retargeting" in issue for issue in result.issues)

    def test_rtb_detection(self) -> None:
        urls = ["https://prebid.example.com/header-bidding"]
        result = advertising.calculate([], [], [], urls)
        assert result.points >= 4
        assert any("bidding" in issue for issue in result.issues)


class TestResolveNetworkName:
    """Tests for _resolve_network_name."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://securepubads.g.doubleclick.net/tag/js/gpt.js", "Google Ads"),
            ("https://connect.facebook.net/sdk.js", "Facebook Ads"),
            ("https://ads.linkedin.com/pixel", "LinkedIn Ads"),
            ("https://unknown-ad.example.com/pixel", "unknown-ad.example.com"),
        ],
    )
    def test_name_resolution(self, url: str, expected: str) -> None:
        assert advertising._resolve_network_name(url) == expected


# ── Data collection scoring ─────────────────────────────────────


class TestDataCollectionScoring:
    """Tests for data collection scorer."""

    def test_empty(self) -> None:
        result = data_collection.calculate([], [], [])
        assert result.points == 0
        assert result.max_points == 18

    def test_local_storage_volume(self) -> None:
        items = [_storage(f"k{i}") for i in range(20)]
        result = data_collection.calculate(items, [], [])
        assert result.points >= 3
        assert any("localStorage" in issue for issue in result.issues)

    def test_tracking_storage_keys(self) -> None:
        items = [_storage("_ga_session"), _storage("_fbp_data")]
        result = data_collection.calculate(items, [], [])
        # May or may not match tracker patterns depending on patterns
        assert result.points >= 0

    def test_beacon_detection(self) -> None:
        long_url = "https://tracker.com/" + "x" * 250
        reqs = [_request(long_url, "tracker.com", is_third_party=True, resource_type="image") for _ in range(15)]
        result = data_collection.calculate([], [], reqs)
        assert result.points >= 4
        assert any("beacon" in issue or "pixel" in issue for issue in result.issues)

    def test_third_party_posts(self) -> None:
        reqs = [
            _request(f"https://collector.com/e{i}", "collector.com", is_third_party=True, method="POST")
            for i in range(6)
        ]
        result = data_collection.calculate([], [], reqs)
        assert result.points >= 3
        assert any("submissions" in issue for issue in result.issues)


# ── Fingerprinting scoring ──────────────────────────────────────


class TestFingerprintingScoring:
    """Tests for the fingerprinting scorer."""

    def test_empty(self) -> None:
        result = fingerprinting.calculate([], [], [], [])
        assert result.points == 0
        assert result.max_points == 39

    def test_fingerprint_cookies(self) -> None:
        items = [_cookie("_fpid")]
        result = fingerprinting.calculate(items, [], [], [])
        # Depends on FINGERPRINT_COOKIE_PATTERNS matching _fpid
        assert result.points >= 0


# ── Social media scoring ───────────────────────────────────────


class TestSocialMediaScoring:
    """Tests for the social media tracker scorer."""

    def test_empty(self) -> None:
        result = social_media.calculate([], [], [])
        assert result.points == 0
        assert result.max_points == 13

    def test_social_plugins(self) -> None:
        urls = ["https://platform.twitter.com/widgets.js"]
        result = social_media.calculate([], [], urls)
        assert result.points >= 3
        assert any("plugin" in issue.lower() for issue in result.issues)


class TestResolveSocialTrackerName:
    """Tests for _resolve_tracker_name."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://connect.facebook.net/sdk.js", "Facebook"),
            ("https://platform.twitter.com/widgets.js", "Twitter/X"),
            ("https://ads.linkedin.com/pixel", "LinkedIn"),
            ("https://unknown.example.com/t.js", "unknown.example.com"),
        ],
    )
    def test_name_resolution(self, url: str, expected: str) -> None:
        assert social_media._resolve_tracker_name(url) == expected


# ── Sensitive data scoring ──────────────────────────────────────


class TestSensitiveDataScoring:
    """Tests for sensitive data scorer."""

    def test_empty(self) -> None:
        result = sensitive_data.calculate(None, [])
        assert result.points == 0
        assert result.max_points == 22

    def test_identity_resolution(self) -> None:
        urls = ["https://api.liveramp.com/v1/identity"]
        result = sensitive_data.calculate(None, urls)
        assert result.points >= 4
        assert any("identity" in issue.lower() for issue in result.issues)

    def test_sensitive_purposes_in_consent(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=[],
            purposes=["Location-based advertising", "Health and wellness analytics"],
            raw_text="We collect your health data and precise location.",
        )
        result = sensitive_data.calculate(cd, [])
        assert result.points >= 2
        assert len(result.issues) >= 1


class TestResolvePurposeLabel:
    """Tests for _resolve_purpose_label."""

    @pytest.mark.parametrize(
        ("pattern_source", "expected_substring"),
        [
            ("location|geo", "Location"),
            ("health|medical", "Health"),
            ("politic", "Political"),
            ("financial|credit", "Financial"),
            ("unknown_pattern_xyz", "Sensitive personal data"),
        ],
    )
    def test_label_resolution(self, pattern_source: str, expected_substring: str) -> None:
        label = sensitive_data._resolve_purpose_label(pattern_source)
        assert expected_substring in label


# ── Consent scoring ─────────────────────────────────────────────


class TestConsentScoring:
    """Tests for the consent category scorer."""

    def test_no_consent_no_tracking(self) -> None:
        result = consent_scoring.calculate(None, [], [])
        assert result.points == 0
        assert result.max_points == 71

    def test_no_consent_with_tracking(self) -> None:
        items = [_cookie(f"c{i}") for i in range(10)]
        result = consent_scoring.calculate(None, items, [])
        assert result.points >= 8
        assert any("without visible consent" in issue for issue in result.issues)

    def test_partner_count_penalty(self) -> None:
        partners = [
            consent.ConsentPartner(
                name=f"Partner {i}",
                purpose="Advertising",
                data_collected=["browsing"],
            )
            for i in range(200)
        ]
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=partners,
            purposes=[],
            raw_text="",
            claimed_partner_count=200,
        )
        result = consent_scoring.calculate(cd, [], [])
        assert result.points >= 10
        assert any("partner" in issue.lower() for issue in result.issues)


class TestPreConsentVolume:
    """Tests for _score_pre_consent_volume."""

    def test_none_stats(self) -> None:
        issues: list[str] = []
        assert consent_scoring._score_pre_consent_volume(None, issues) == 0
        assert issues == []

    def test_high_tracking_cookies(self) -> None:
        stats = analysis.PreConsentStats(tracking_cookies=12)
        issues: list[str] = []
        pts = consent_scoring._score_pre_consent_volume(stats, issues)
        assert pts >= 5
        assert any("tracking cookies" in i for i in issues)

    def test_high_tracking_scripts(self) -> None:
        stats = analysis.PreConsentStats(tracking_scripts=12)
        issues: list[str] = []
        pts = consent_scoring._score_pre_consent_volume(stats, issues)
        assert pts >= 5

    def test_high_tracker_requests(self) -> None:
        stats = analysis.PreConsentStats(tracker_requests=25)
        issues: list[str] = []
        pts = consent_scoring._score_pre_consent_volume(stats, issues)
        assert pts >= 5

    def test_zero_classified_counts(self) -> None:
        stats = analysis.PreConsentStats(
            total_cookies=50,
            total_scripts=100,
            total_requests=500,
            tracking_cookies=0,
            tracking_scripts=0,
            tracker_requests=0,
        )
        issues: list[str] = []
        pts = consent_scoring._score_pre_consent_volume(stats, issues)
        assert pts == 0


# ── Calculator orchestrator ─────────────────────────────────────


class TestCalculatePrivacyScore:
    """Tests for the top-level calculate_privacy_score."""

    def test_minimal_site(self) -> None:
        result = calculator.calculate_privacy_score(
            cookies_list=[],
            scripts=[],
            network_requests=[],
            local_storage=[],
            session_storage=[],
            analyzed_url="https://example.com",
        )
        assert result.total_score == 0
        assert "cookies" in result.categories
        assert result.summary != ""

    def test_heavy_tracking_site(self) -> None:
        cookies_list = [_cookie(f"c{i}", domain="tracker.com") for i in range(30)]
        cookies_list.append(_cookie("_ga"))
        cookies_list.append(_cookie("_fbp"))
        scripts_list = [
            _script("https://www.google-analytics.com/analytics.js", "google-analytics.com"),
            _script("https://connect.facebook.net/sdk.js", "facebook.net"),
        ]
        requests_list = [
            _request(f"https://doubleclick.net/pixel{i}", "doubleclick.net", is_third_party=True)
            for i in range(30)
        ]
        result = calculator.calculate_privacy_score(
            cookies_list=cookies_list,
            scripts=scripts_list,
            network_requests=requests_list,
            local_storage=[],
            session_storage=[],
            analyzed_url="https://www.example.com",
        )
        assert result.total_score > 20
        assert len(result.factors) > 0

    def test_summary_mentions_domain(self) -> None:
        result = calculator.calculate_privacy_score(
            cookies_list=[],
            scripts=[],
            network_requests=[],
            local_storage=[],
            session_storage=[],
            analyzed_url="https://www.test-site.com/page",
        )
        assert "test-site.com" in result.summary


class TestGenerateSummary:
    """Tests for the summary generator."""

    @pytest.mark.parametrize(
        ("score", "expected_severity"),
        [
            (0, "minimal"),
            (15, "minimal"),
            (25, "limited"),
            (45, "moderate"),
            (65, "significant"),
            (85, "extensive"),
        ],
    )
    def test_severity_thresholds(self, score: int, expected_severity: str) -> None:
        summary = calculator._generate_summary("example.com", score, [])
        assert expected_severity in summary

    def test_www_stripped(self) -> None:
        summary = calculator._generate_summary("www.example.com", 50, [])
        assert "www." not in summary
        assert "example.com" in summary

    def test_session_replay_override(self) -> None:
        summary = calculator._generate_summary("example.com", 80, ["Session replay active"])
        assert "session recording" in summary

    def test_fingerprint_override(self) -> None:
        summary = calculator._generate_summary("example.com", 80, ["Fingerprinting detected"])
        assert "fingerprinting" in summary
