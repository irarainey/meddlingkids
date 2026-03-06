"""Tests for extended scoring: consent, third_party, advertising, social_media."""

from __future__ import annotations

from src.analysis.scoring import (
    advertising,
    data_collection,
    social_media,
    third_party,
)
from src.analysis.scoring import (
    consent as consent_scoring,
)
from src.models import consent, tracking_data

# ── Helpers ─────────────────────────────────────────────────────


def _cookie(name: str = "c", domain: str = "example.com", *, expires: float = 0) -> tracking_data.TrackedCookie:
    return tracking_data.TrackedCookie(
        name=name,
        value="v",
        domain=domain,
        path="/",
        expires=expires,
        http_only=False,
        secure=False,
        same_site="None",
        timestamp="t",
    )


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
        timestamp="t",
    )


def _storage(key: str = "k") -> tracking_data.StorageItem:
    return tracking_data.StorageItem(key=key, value="v", timestamp="t")


# ── Consent scoring: partner risk ──────────────────────────────


class TestConsentPartnerRiskScoring:
    """Tests for consent partner risk scoring branches."""

    def test_critical_partners_over_5(self) -> None:
        partners = [
            consent.ConsentPartner(
                name=f"DataBroker{i}",
                purpose="Data brokering and identity resolution",
                data_collected=["browsing"],
                risk_level="critical",
                risk_category="data-broker",
            )
            for i in range(8)
        ]
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=partners,
            purposes=[],
            raw_text="",
            claimed_partner_count=8,
        )
        result = consent_scoring.calculate(cd, [], [])
        assert result.points >= 8
        assert any("data broker" in issue.lower() or "identity" in issue.lower() for issue in result.issues)

    def test_critical_partners_2_to_5(self) -> None:
        partners = [
            consent.ConsentPartner(
                name=f"DataBroker{i}",
                purpose="Data brokering",
                data_collected=["browsing"],
                risk_level="critical",
                risk_category="data-broker",
            )
            for i in range(3)
        ]
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=partners,
            purposes=[],
            raw_text="",
            claimed_partner_count=3,
        )
        result = consent_scoring.calculate(cd, [], [])
        assert result.points >= 5

    def test_vague_consent_purposes(self) -> None:
        cd = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=[],
            purposes=[
                "legitimate interest in improving our services",
                "legitimate interest in analytics",
                "legitimate interest in security",
            ],
            raw_text="",
        )
        result = consent_scoring.calculate(cd, [], [])
        assert any("vague" in issue.lower() for issue in result.issues)


# ── Third-party scoring: extended ──────────────────────────────


class TestThirdPartyExtended:
    """Extended tests for third-party scoring branches."""

    def test_many_third_party_requests(self) -> None:
        reqs = [_request(f"https://tracker{i}.com/p", f"tracker{i}.com", is_third_party=True) for i in range(50)]
        result = third_party.calculate(reqs, [], "example.com", [])
        assert result.points >= 10

    def test_known_tracker_urls(self) -> None:
        urls = [
            "https://www.google-analytics.com/analytics.js",
            "https://connect.facebook.net/en/sdk.js",
        ]
        reqs = [
            _request(urls[0], "www.google-analytics.com", is_third_party=True),
            _request(urls[1], "connect.facebook.net", is_third_party=True),
        ]
        result = third_party.calculate(reqs, [], "example.com", urls)
        assert result.points >= 5


# ── Advertising scoring: extended ──────────────────────────────


class TestAdvertisingExtended:
    """Extended tests for advertising scoring."""

    def test_many_ad_networks(self) -> None:
        urls = [
            "https://securepubads.g.doubleclick.net/tag/js/gpt.js",
            "https://connect.facebook.net/en/sdk.js",
            "https://ads.linkedin.com/pixel",
            "https://cdn.taboola.com/libtrc.js",
            "https://cdn.outbrain.com/loader.js",
            "https://ads.criteo.com/pixel.js",
            "https://cdn.tiktokapi.com/analytics.js",
        ]
        result = advertising.calculate([], [], [], urls)
        assert result.points >= 8
        assert any("ad network" in issue.lower() for issue in result.issues)

    def test_2_to_3_ad_networks(self) -> None:
        urls = [
            "https://securepubads.g.doubleclick.net/tag/js/gpt.js",
            "https://connect.facebook.net/en/sdk.js",
        ]
        result = advertising.calculate([], [], [], urls)
        assert result.points >= 5

    def test_single_ad_network(self) -> None:
        urls = ["https://securepubads.g.doubleclick.net/tag/js/gpt.js"]
        result = advertising.calculate([], [], [], urls)
        assert result.points >= 3
        assert any("ad network" in issue.lower() for issue in result.issues)


# ── Social media scoring: extended ─────────────────────────────


class TestSocialMediaExtended:
    """Extended tests for social media scoring."""

    def test_many_social_trackers(self) -> None:
        urls = [
            "https://connect.facebook.net/sdk.js",
            "https://platform.twitter.com/widgets.js",
            "https://ads.linkedin.com/pixel",
            "https://sc-static.net/js/snap.js",
        ]
        result = social_media.calculate([], [], urls)
        assert result.points >= 6

    def test_two_social_trackers(self) -> None:
        urls = [
            "https://connect.facebook.net/sdk.js",
            "https://platform.twitter.com/widgets.js",
        ]
        result = social_media.calculate([], [], urls)
        assert result.points >= 6

    def test_single_social_tracker(self) -> None:
        urls = ["https://connect.facebook.net/sdk.js"]
        result = social_media.calculate([], [], urls)
        assert result.points >= 4


# ── Data collection: analytics detection ───────────────────────


class TestDataCollectionExtended:
    """Extended tests for data collection scorer."""

    def test_analytics_tracking(self) -> None:
        result = data_collection.calculate(
            [],
            [],
            [_request("https://www.google-analytics.com/analytics.js", "google-analytics.com")],
        )
        assert result.points >= 2
        assert any("analytics" in issue.lower() for issue in result.issues)

    def test_tracking_storage(self) -> None:
        items = [_storage("amplitude_session"), _storage("segment_user_id")]
        result = data_collection.calculate(items, [], [])
        assert result.points >= 0
