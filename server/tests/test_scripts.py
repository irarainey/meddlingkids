"""Tests for src.analysis.scripts — script identification layers."""

from __future__ import annotations

from src.analysis import scripts


class TestIdentifyTrackerDomain:
    """Tests for the tracker-domain lookup layer."""

    def test_known_tracker_domain_returns_description(self) -> None:
        desc = scripts._identify_tracker_domain("doubleclick.net")
        assert desc is not None
        assert "Known tracker" in desc

    def test_known_tracker_includes_company(self) -> None:
        desc = scripts._identify_tracker_domain("doubleclick.net")
        assert desc is not None
        # doubleclick.net is in disconnect-services with a company name
        assert "Google" in desc or "Advertising" in desc

    def test_tracker_domain_only_returns_generic(self) -> None:
        """A domain in tracker-domains but NOT in disconnect should
        return a generic label."""
        desc = scripts._identify_tracker_domain("fingerprint.com")
        assert desc is not None
        assert "Known track" in desc

    def test_unknown_domain_returns_none(self) -> None:
        desc = scripts._identify_tracker_domain("not-a-tracker.example")
        assert desc is None

    def test_first_party_domain_returns_none(self) -> None:
        desc = scripts._identify_tracker_domain("example.com")
        assert desc is None


class TestIdentifyTrackingScript:
    """Tests for the regex-based tracking script identification."""

    def test_known_tracking_script_matched(self) -> None:
        desc = scripts._identify_tracking_script(
            "https://www.googletagmanager.com/gtm.js?id=GTM-XXXX",
        )
        assert desc is not None

    def test_unknown_script_not_matched(self) -> None:
        desc = scripts._identify_tracking_script(
            "https://example.com/app.js",
        )
        assert desc is None


class TestIdentifyBenignScript:
    """Tests for the regex-based benign script identification."""

    def test_known_benign_not_matched_as_tracking(self) -> None:
        # jQuery CDN should not be flagged as tracking
        desc = scripts._identify_tracking_script(
            "https://code.jquery.com/jquery-3.6.0.min.js",
        )
        assert desc is None
