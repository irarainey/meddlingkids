"""Extended tests for fingerprinting and sensitive-data scoring.

Covers uncovered branches in session-replay, cross-device,
behavioural tracking, and location/ISP/profiling scoring.
"""

from __future__ import annotations

import pytest

from src.analysis.scoring import fingerprinting, sensitive_data
from src.models import consent, tracking_data

# ── Helpers ─────────────────────────────────────────────────────


def _cookie(name: str = "c", domain: str = "example.com") -> tracking_data.TrackedCookie:
    return tracking_data.TrackedCookie(
        name=name,
        value="v",
        domain=domain,
        path="/",
        expires=0,
        http_only=False,
        secure=False,
        same_site="None",
        timestamp="t",
    )


def _script(url: str = "https://example.com/app.js", domain: str = "example.com") -> tracking_data.TrackedScript:
    return tracking_data.TrackedScript(url=url, domain=domain)


def _request(
    url: str = "https://example.com/api",
    domain: str = "example.com",
    *,
    is_third_party: bool = False,
) -> tracking_data.NetworkRequest:
    return tracking_data.NetworkRequest(
        url=url,
        domain=domain,
        method="GET",
        resource_type="xhr",
        is_third_party=is_third_party,
        timestamp="t",
    )


# ── Fingerprinting: session replay ─────────────────────────────


class TestSessionReplayScoring:
    """Tests for session replay detection in fingerprinting scorer."""

    def test_single_session_replay(self) -> None:
        urls = ["https://static.hotjar.com/c/hotjar.js"]
        result = fingerprinting.calculate([], [], [], urls)
        assert result.points >= 10
        assert any("session replay" in issue.lower() for issue in result.issues)

    def test_multiple_session_replay(self) -> None:
        urls = [
            "https://static.hotjar.com/c/hotjar.js",
            "https://cdn.fullstory.com/s/fs.js",
        ]
        result = fingerprinting.calculate([], [], [], urls)
        assert result.points >= 12
        assert any("multiple session replay" in issue.lower() for issue in result.issues)


# ── Fingerprinting: cross-device ───────────────────────────────


class TestCrossDeviceScoring:
    """Tests for cross-device identity tracking detection."""

    def test_cross_device_tracker(self) -> None:
        urls = ["https://api.liveramp.com/v1/identity"]
        result = fingerprinting.calculate([], [], [], urls)
        assert result.points >= 8
        assert any("cross-device" in issue.lower() for issue in result.issues)

    def test_cross_device_tapad(self) -> None:
        urls = ["https://cdn.tapad.com/tapestry/js"]
        result = fingerprinting.calculate([], [], [], urls)
        assert result.points >= 8


# ── Fingerprinting: behavioural tracking ───────────────────────


class TestBehaviouralTrackingScoring:
    """Tests for behavioural engagement tracking detection."""

    def test_scroll_tracking(self) -> None:
        urls = ["https://example.com/scroll-depth-tracker.js"]
        result = fingerprinting.calculate([], [], [], urls)
        assert any("scroll" in issue.lower() or "attention" in issue.lower() for issue in result.issues)

    def test_video_tracking(self) -> None:
        urls = ["https://cdn.conviva.com/conviva.js"]
        result = fingerprinting.calculate([], [], [], urls)
        assert any("video" in issue.lower() for issue in result.issues)

    def test_mouse_heatmap_tracking(self) -> None:
        urls = ["https://cdn.crazy-egg.com/crazy-egg.js"]
        result = fingerprinting.calculate([], [], [], urls)
        assert any("mouse" in issue.lower() or "heatmap" in issue.lower() for issue in result.issues)

    def test_eye_tracking(self) -> None:
        urls = ["https://cdn.tobii.com/gaze-tracker.js"]
        result = fingerprinting.calculate([], [], [], urls)
        assert any("eye" in issue.lower() or "gaze" in issue.lower() for issue in result.issues)

    def test_rage_click_tracking(self) -> None:
        urls = ["https://analytics.example.com/rage-click-detector.js"]
        result = fingerprinting.calculate([], [], [], urls)
        assert any("rage" in issue.lower() or "frustrat" in issue.lower() for issue in result.issues)

    def test_multiple_behavioural_categories(self) -> None:
        urls = [
            "https://example.com/scroll-depth.js",
            "https://cdn.conviva.com/conviva.js",
            "https://cdn.crazy-egg.com/crazy-egg.js",
            "https://cdn.tobii.com/eye-tracker.js",
        ]
        result = fingerprinting.calculate([], [], [], urls)
        # Multiple behaviour categories → capped at 10 points
        assert result.points >= 3


# ── Fingerprinting: fingerprint cookies ────────────────────────


class TestFingerprintCookieScoring:
    """Tests for fingerprint-related cookie detection."""

    def test_fingerprint_cookie(self) -> None:
        cookies = [_cookie("fingerprint_id")]
        result = fingerprinting.calculate(cookies, [], [], [])
        assert result.points >= 3
        assert any("fingerprint" in issue.lower() for issue in result.issues)

    def test_device_id_cookie(self) -> None:
        cookies = [_cookie("device_id")]
        result = fingerprinting.calculate(cookies, [], [], [])
        assert result.points >= 3


# ── Fingerprinting: other fingerprinters ───────────────────────


class TestOtherFingerprinters:
    """Tests for general fingerprinting services (not session replay)."""

    def test_multiple_fingerprint_services(self) -> None:
        urls = [
            "https://fpjs.example.com/v3",
            "https://bluekai.oracle.com/r",
            "https://cdn.oracle.com/cloud/data.js",
        ]
        result = fingerprinting.calculate([], [], [], urls)
        assert result.points >= 4


# ── Sensitive data: location tracking ──────────────────────────


class TestLocationTrackingScoring:
    """Tests for granular location / ISP scoring."""

    def test_ip_geolocation(self) -> None:
        urls = ["https://ipinfo.io/json"]
        result = sensitive_data.calculate(None, urls)
        assert result.points >= 3
        assert any("ip" in issue.lower() or "geolocation" in issue.lower() for issue in result.issues)

    def test_postcode_tracking(self) -> None:
        urls = ["https://api.example.com/postcode-lookup"]
        result = sensitive_data.calculate(None, urls)
        assert result.points >= 6
        assert any("postcode" in issue.lower() or "granular" in issue.lower() for issue in result.issues)

    def test_precise_gps(self) -> None:
        urls = ["https://api.example.com/precise-location"]
        result = sensitive_data.calculate(None, urls)
        assert result.points >= 6
        assert any("granular" in issue.lower() for issue in result.issues)

    def test_isp_tracking(self) -> None:
        urls = ["https://api.example.com/isp-detect"]
        result = sensitive_data.calculate(None, urls)
        assert result.points >= 4
        assert any("isp" in issue.lower() for issue in result.issues)

    def test_geofencing(self) -> None:
        urls = ["https://api.example.com/geo-target"]
        result = sensitive_data.calculate(None, urls)
        assert result.points >= 3
        assert len(result.issues) >= 1


# ── Sensitive data: content profiling ──────────────────────────


class TestContentProfilingScoring:
    """Tests for content topic profiling detection."""

    def test_profiling_service(self) -> None:
        urls = ["https://cdn.grapeshot.co.uk/gs-cat.js"]
        result = sensitive_data.calculate(None, urls)
        assert result.points >= 4
        assert any("profiling" in issue.lower() for issue in result.issues)

    def test_multiple_profiling_services(self) -> None:
        urls = [
            "https://cdn.grapeshot.co.uk/gs-cat.js",
            "https://cdn.permutive.com/a.js",
            "https://cdn.peer39.com/topic.js",
        ]
        result = sensitive_data.calculate(None, urls)
        assert result.points >= 6

    def test_audience_segmentation(self) -> None:
        urls = ["https://api.permutive.com/v1/audience-segment"]
        result = sensitive_data.calculate(None, urls)
        assert result.points >= 4


# ── Sensitive data: sensitive purposes ─────────────────────────


class TestSensitivePurposeScoring:
    """Tests for consent-disclosed sensitive data categories."""

    def test_multiple_sensitive_purposes(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=[],
            purposes=["Location-based targeting", "Health analytics", "Political advertising"],
            raw_text="We track your location, health data, and political interests.",
        )
        result = sensitive_data.calculate(cd, [])
        assert result.points >= 4
        assert len(result.issues) >= 3

    def test_financial_purpose(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=[],
            purposes=["financial data tracking"],
            raw_text="We collect credit score data.",
        )
        result = sensitive_data.calculate(cd, [])
        assert any("financial" in issue.lower() for issue in result.issues)

    def test_pregnancy_purpose(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="pregnancy tracking and baby data collection",
        )
        result = sensitive_data.calculate(cd, [])
        assert any("pregnan" in issue.lower() or "fertility" in issue.lower() for issue in result.issues)

    def test_child_data_purpose(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[
                consent.ConsentCategory(
                    name="Children",
                    description="Data collection about children and minors",
                    required=False,
                ),
            ],
            partners=[],
            purposes=[],
            raw_text="",
        )
        result = sensitive_data.calculate(cd, [])
        assert any("child" in issue.lower() for issue in result.issues)

    def test_no_sensitive_purposes(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=[],
            purposes=["Basic analytics"],
            raw_text="We use basic analytics.",
        )
        result = sensitive_data.calculate(cd, [])
        # No sensitive-purpose points
        assert result.points == 0


class TestResolvePurposeLabelExtra:
    """Additional tests for _resolve_purpose_label."""

    @pytest.mark.parametrize(
        ("pattern_source", "expected_substring"),
        [
            ("pregnan|fertility", "Pregnancy"),
            ("mental.?health|depression", "Health"),
            ("addiction|gambling", "Addiction"),
            ("child|minor", "Child"),
            ("criminal|arrest", "Criminal"),
            ("disabilit", "Disability"),
            ("religio", "Religious"),
            ("ethnic|racial", "Ethnic"),
            ("sexual|sex", "Sexual"),
            ("immigration|visa", "Immigration"),
            ("trade.?union", "Sensitive personal data"),
            ("legal.?aid|solicitor", "Legal"),
        ],
    )
    def test_label_resolution(self, pattern_source: str, expected_substring: str) -> None:
        label = sensitive_data._resolve_purpose_label(pattern_source)
        assert expected_substring in label


class TestDetectBehaviouralTracking:
    """Tests for _detect_behavioural_tracking()."""

    def test_empty_urls(self) -> None:
        assert fingerprinting._detect_behavioural_tracking([]) == []

    def test_no_matches(self) -> None:
        assert fingerprinting._detect_behavioural_tracking(["https://example.com/app.js"]) == []

    def test_deduplicated(self) -> None:
        urls = [
            "https://example.com/scroll-depth-1.js",
            "https://example.com/scroll-depth-2.js",
        ]
        result = fingerprinting._detect_behavioural_tracking(urls)
        # Same category should appear only once
        scroll_labels = [r for r in result if "scroll" in r.lower()]
        assert len(scroll_labels) <= 1
