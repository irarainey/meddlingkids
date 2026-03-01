"""Tests for src.analysis.tracker_patterns — regex pattern classification."""

from __future__ import annotations

import pytest

from src.analysis import tracker_patterns


class TestHighRiskTrackers:
    """Tests for HIGH_RISK_TRACKERS patterns."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://cdn.fingerprint.com/v3/loader.js",
            "https://fpjs.io/sdk.js",
            "https://clarity.ms/tag/abc123",
            "https://api.fullstory.com/events",
            "https://static.hotjar.com/c/hotjar.js",
            "https://api.logrocket.com/sessions",
            "https://cdn.mouseflow.com/track.js",
            "https://cdn.smartlook.com/recorder.js",
            "https://bluekai.com/pixel.gif",
            "https://liveramp.com/identity",
            "https://cdn.id5-sync.com/api.js",
            "https://match.adsrvr.org/track",
        ],
    )
    def test_high_risk_matches(self, url: str) -> None:
        assert any(p.search(url) for p in tracker_patterns.HIGH_RISK_TRACKERS)

    def test_benign_url_not_matched(self) -> None:
        assert not any(p.search("https://cdn.example.com/app.js") for p in tracker_patterns.HIGH_RISK_TRACKERS)


class TestAdvertisingTrackers:
    """Tests for ADVERTISING_TRACKERS patterns."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://ad.doubleclick.net/pixel",
            "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js",
            "https://www.googleadservices.com/pagead/conversion/",
            "https://connect.facebook.net/en_US/fbevents.js",
            "https://ads.amazon-adsystem.com/aax2/apstag.js",
            "https://static.criteo.net/js/ld/ld.js",
            "https://cdn.taboola.com/loader.js",
            "https://bat.bing.com/bat.js",
        ],
    )
    def test_advertising_matches(self, url: str) -> None:
        assert any(p.search(url) for p in tracker_patterns.ADVERTISING_TRACKERS)


class TestAnalyticsTrackers:
    """Tests for ANALYTICS_TRACKERS patterns."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.google-analytics.com/analytics.js",
            "https://www.googletagmanager.com/gtag/js",
            "https://cdn.segment.com/analytics.min.js",
            "https://cdn.amplitude.com/libs/amplitude.min.js",
            "https://cdn.mixpanel.com/mixpanel.min.js",
        ],
    )
    def test_analytics_matches(self, url: str) -> None:
        assert any(p.search(url) for p in tracker_patterns.ANALYTICS_TRACKERS)


class TestTrackingCookiePatterns:
    """Tests for TRACKING_COOKIE_PATTERNS."""

    @pytest.mark.parametrize(
        "cookie_name",
        ["_ga", "_gid", "_gat", "_fbp", "_fbc", "_gcl_au", "_uetmsclkid", "__utma", "_hjid", "_clck", "IDE", "fr"],
    )
    def test_tracking_cookie_matches(self, cookie_name: str) -> None:
        assert any(p.search(cookie_name) for p in tracker_patterns.TRACKING_COOKIE_PATTERNS)

    @pytest.mark.parametrize(
        "cookie_name",
        ["session_id", "theme", "language", "csrf_token"],
    )
    def test_benign_cookie_not_matched(self, cookie_name: str) -> None:
        assert not any(p.search(cookie_name) for p in tracker_patterns.TRACKING_COOKIE_PATTERNS)


class TestCombinedPatterns:
    """Tests for pre-compiled combined alternation patterns."""

    def test_tracking_cookie_combined_matches(self) -> None:
        assert tracker_patterns.TRACKING_COOKIE_COMBINED.search("_ga")
        assert tracker_patterns.TRACKING_COOKIE_COMBINED.search("_fbp")

    def test_tracking_cookie_combined_no_match(self) -> None:
        assert not tracker_patterns.TRACKING_COOKIE_COMBINED.search("preferences")

    def test_url_trackers_combined_matches(self) -> None:
        assert tracker_patterns.ALL_URL_TRACKERS_COMBINED.search("https://doubleclick.net/pixel")
        assert tracker_patterns.ALL_URL_TRACKERS_COMBINED.search("https://clarity.ms/track")

    def test_url_trackers_combined_no_match(self) -> None:
        assert not tracker_patterns.ALL_URL_TRACKERS_COMBINED.search("https://example.com/app.js")


class TestSensitivePurposes:
    """Tests for SENSITIVE_PURPOSES patterns."""

    @pytest.mark.parametrize(
        "purpose",
        [
            "political advertising",
            "health data collection",
            "financial tracking",
            "location-based ads",
            "child protection",
        ],
    )
    def test_sensitive_purpose_matches(self, purpose: str) -> None:
        assert any(p.search(purpose) for p in tracker_patterns.SENSITIVE_PURPOSES)

    def test_non_sensitive_purpose(self) -> None:
        assert not any(p.search("general website analytics") for p in tracker_patterns.SENSITIVE_PURPOSES)


class TestSessionReplayPatterns:
    """Tests for SESSION_REPLAY_PATTERNS."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://static.hotjar.com/c/hotjar.js",
            "https://api.fullstory.com/events",
            "https://cdn.mouseflow.com/track.js",
            "https://clarity.ms/tag/abc",
        ],
    )
    def test_session_replay_matches(self, url: str) -> None:
        assert any(p.search(url) for p in tracker_patterns.SESSION_REPLAY_PATTERNS)


class TestConsentStateCookiePatterns:
    """Tests for CONSENT_STATE_COOKIE_PATTERNS."""

    @pytest.mark.parametrize(
        "cookie_name",
        [
            "euconsent-v2",
            "euconsent",
            "addtl_consent",
            "usprivacy",
            "OptanonConsent",
            "OptanonAlertBoxClosed",
            "CookieConsent",
            "didomi_token",
            "cmplz_marketing",
            "cmplz_statistics",
            "__cmpcc",
            "cookielawinfo-checkbox-analytics",
            "sp_consent",
            "consentUUID",
            "truste.eu.cookie.notice",
            "notice_behavior",
            "notice_preferences",
            "CONSENTMGR",
            "SOCS",
            "GPC_SIGNAL",
        ],
    )
    def test_consent_cookie_matches(self, cookie_name: str) -> None:
        assert any(p.search(cookie_name) for p in tracker_patterns.CONSENT_STATE_COOKIE_PATTERNS)

    @pytest.mark.parametrize(
        "cookie_name",
        [
            "_ga",
            "_fbp",
            "IDE",
            "session_id",
            "theme",
            "language",
        ],
    )
    def test_tracking_not_consent(self, cookie_name: str) -> None:
        """Tracking and benign cookies should not match consent patterns."""
        assert not any(p.search(cookie_name) for p in tracker_patterns.CONSENT_STATE_COOKIE_PATTERNS)

    def test_consent_combined_matches(self) -> None:
        assert tracker_patterns.CONSENT_STATE_COOKIE_COMBINED.search("euconsent-v2")
        assert tracker_patterns.CONSENT_STATE_COOKIE_COMBINED.search("OptanonConsent")
        assert tracker_patterns.CONSENT_STATE_COOKIE_COMBINED.search("usprivacy")

    def test_consent_combined_no_false_positive(self) -> None:
        assert not tracker_patterns.CONSENT_STATE_COOKIE_COMBINED.search("_ga")


class TestTcfIndicators:
    """Tests for TCF_INDICATORS patterns."""

    @pytest.mark.parametrize(
        "text",
        [
            "__tcfapi",
            "euconsent-v2",
            "iab vendor list",
            "transparency consent framework",
            "transparencyandconsent",
            "__cmp(",
            "cmpapi",
            "gdpr_consent",
        ],
    )
    def test_tcf_indicator_matches(self, text: str) -> None:
        assert any(p.search(text) for p in tracker_patterns.TCF_INDICATORS)

    def test_tcf_combined_matches(self) -> None:
        assert tracker_patterns.TCF_INDICATORS_COMBINED.search("window.__tcfapi")

    def test_tcf_combined_no_match(self) -> None:
        assert not tracker_patterns.TCF_INDICATORS_COMBINED.search("regular javascript code")
