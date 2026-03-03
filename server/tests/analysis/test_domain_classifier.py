"""Tests for src.analysis.domain_classifier.

Covers deterministic domain classification using Disconnect
and partner databases, multi-category prioritisation, the
tracking-section builder, and the merge helper.
"""

from __future__ import annotations

from unittest import mock

from src.analysis.domain_classifier import (
    _best_disconnect_category,
    build_deterministic_tracking_section,
    classify_domain,
    merge_tracking_sections,
)
from src.models import analysis, partners, report

# ── _best_disconnect_category ──────────────────────────────────


class TestBestDisconnectCategory:
    """Priority-based selection from multi-category entries."""

    def test_social_beats_fingerprinting(self) -> None:
        """Social is preferred over FingerprintingGeneral."""
        result = _best_disconnect_category(
            ["FingerprintingGeneral", "Social"],
        )
        assert result == "social_media"

    def test_advertising_beats_fingerprinting(self) -> None:
        """Advertising is preferred over FingerprintingGeneral."""
        result = _best_disconnect_category(
            ["FingerprintingGeneral", "Advertising"],
        )
        assert result == "advertising"

    def test_social_beats_advertising(self) -> None:
        """Social is preferred over Advertising."""
        result = _best_disconnect_category(
            ["Advertising", "Social"],
        )
        assert result == "social_media"

    def test_single_category(self) -> None:
        """Single-element list returns the mapped value."""
        assert _best_disconnect_category(["Analytics"]) == "analytics"

    def test_all_other_categories(self) -> None:
        """When all categories map to 'other', return 'other'."""
        result = _best_disconnect_category(
            ["Content", "Email"],
        )
        assert result == "other"

    def test_empty_list(self) -> None:
        """Empty list returns 'other'."""
        assert _best_disconnect_category([]) == "other"

    def test_unknown_raw_category(self) -> None:
        """Unrecognised raw categories are skipped."""
        result = _best_disconnect_category(
            ["MadeUpCategory", "Analytics"],
        )
        assert result == "analytics"

    def test_invasive_beats_general_fingerprinting(self) -> None:
        """FingerprintingInvasive is more specific."""
        result = _best_disconnect_category(
            ["FingerprintingGeneral", "FingerprintingInvasive"],
        )
        assert result == "identity_resolution"


# ── classify_domain ────────────────────────────────────────────


class TestClassifyDomain:
    """Domain classification using Disconnect + partner DBs."""

    def test_disconnect_analytics(self) -> None:
        """google-analytics.com is categorised as analytics."""
        cat, company = classify_domain("google-analytics.com")
        assert cat == "analytics"
        assert company == "Google"

    def test_disconnect_advertising(self) -> None:
        """doubleclick.net is categorised as advertising."""
        cat, company = classify_domain("doubleclick.net")
        assert cat == "advertising"
        assert company == "Google"

    def test_disconnect_social(self) -> None:
        """facebook.com is categorised as social_media."""
        cat, company = classify_domain("facebook.com")
        assert cat == "social_media"
        assert company == "Meta"

    def test_disconnect_social_subdomain(self) -> None:
        """facebook.net is also social_media (multi-cat)."""
        cat, company = classify_domain("facebook.net")
        assert cat == "social_media"
        assert company == "Meta"

    def test_disconnect_analytics_hotjar(self) -> None:
        """hotjar.com is analytics, not overridden by partner."""
        cat, company = classify_domain("hotjar.com")
        assert cat == "analytics"
        assert company is not None

    def test_disconnect_social_twitter(self) -> None:
        """twitter.com is categorised as social_media."""
        cat, _company = classify_domain("twitter.com")
        assert cat == "social_media"

    def test_disconnect_social_linkedin(self) -> None:
        """linkedin.com is categorised as social_media."""
        cat, _company = classify_domain("linkedin.com")
        assert cat == "social_media"

    def test_disconnect_criteo(self) -> None:
        """criteo.com is categorised as advertising."""
        cat, _company = classify_domain("criteo.com")
        assert cat == "advertising"

    def test_unknown_domain(self) -> None:
        """A completely unknown domain returns other/None."""
        cat, company = classify_domain("totally-unknown-xyz.test")
        assert cat == "other"
        assert company is None

    def test_disconnect_priority_over_partner(self) -> None:
        """Disconnect's specific category is not overridden.

        facebook.com appears in both Disconnect (Social) and
        the ad-networks partner DB (Facebook Audience Network).
        Social should win because Disconnect provides domain-
        level classification.
        """
        cat, _ = classify_domain("facebook.com")
        assert cat == "social_media"

    def test_partner_fallback_for_disconnect_other(self) -> None:
        """Partner DB is consulted when Disconnect gives 'other'.

        If a domain is in Disconnect with a category that maps
        to 'other' (e.g. Content, Email), the partner DB can
        provide a more specific classification.
        """
        # Mock Disconnect returning a category that maps to
        # "other" so the partner fallback path activates.
        with (
            mock.patch(
                "src.analysis.domain_classifier.loader.get_disconnect_category",
                return_value="Content",
            ),
            mock.patch(
                "src.analysis.domain_classifier.loader.get_disconnect_services",
                return_value={},
            ),
            mock.patch(
                "src.analysis.domain_classifier.loader.get_partner_database",
                return_value={
                    "TestTracker": partners.PartnerEntry(
                        url="https://test-tracker.example.com",
                        concerns=[],
                        aliases=[],
                    ),
                },
            ),
            mock.patch(
                "src.analysis.domain_classifier.loader.PARTNER_CATEGORIES",
                [
                    partners.PartnerCategoryConfig(
                        file="fake.json",
                        category="analytics",
                        risk_level="low",
                        reason="test",
                        risk_score=1,
                    ),
                ],
            ),
        ):
            cat, company = classify_domain(
                "test-tracker.example.com",
            )
            assert cat == "analytics"
            assert company == "Testtracker"


# ── build_deterministic_tracking_section ───────────────────────


class TestBuildDeterministicTrackingSection:
    """End-to-end tracking section from local databases."""

    @staticmethod
    def _make_summary(
        domains: list[str],
        breakdowns: list[analysis.DomainBreakdown] | None = None,
    ) -> analysis.TrackingSummary:
        """Build a minimal TrackingSummary for testing."""
        return analysis.TrackingSummary(
            analyzed_url="https://example.com",
            total_cookies=0,
            total_scripts=0,
            total_network_requests=0,
            local_storage_items=0,
            session_storage_items=0,
            third_party_domains=domains,
            domain_breakdown=breakdowns or [],
            local_storage=[],
            session_storage=[],
        )

    def test_known_domains_classified(self) -> None:
        """Known domains are placed in correct categories."""
        summary = self._make_summary(
            ["google-analytics.com", "doubleclick.net"],
        )
        section, unclassified = build_deterministic_tracking_section(summary)
        assert len(section.analytics) >= 1
        assert len(section.advertising) >= 1
        assert unclassified == []

    def test_unknown_domains_returned(self) -> None:
        """Unknown domains are listed as unclassified."""
        summary = self._make_summary(
            ["totally-unknown-xyz.test"],
        )
        _section, unclassified = build_deterministic_tracking_section(summary)
        assert unclassified == ["totally-unknown-xyz.test"]

    def test_mixed_known_and_unknown(self) -> None:
        """Mix of known/unknown domains works correctly."""
        summary = self._make_summary(
            [
                "google-analytics.com",
                "not-a-real-tracker.test",
                "doubleclick.net",
            ],
        )
        _section, unclassified = build_deterministic_tracking_section(summary)
        assert len(unclassified) == 1
        assert "not-a-real-tracker.test" in unclassified

    def test_cookies_attached_from_breakdown(self) -> None:
        """Cookie names from domain breakdown are included."""
        bd = analysis.DomainBreakdown(
            domain="google-analytics.com",
            cookie_count=2,
            cookie_names=["_ga", "_gid"],
            script_count=1,
            request_count=3,
            request_types=["script"],
        )
        summary = self._make_summary(
            ["google-analytics.com"],
            breakdowns=[bd],
        )
        section, _ = build_deterministic_tracking_section(summary)
        all_cookies: list[str] = []
        for entry in section.analytics:
            all_cookies.extend(entry.cookies)
        assert "_ga" in all_cookies
        assert "_gid" in all_cookies

    def test_subdomains_grouped_by_company(self) -> None:
        """Multiple subdomains of one company merge entries."""
        summary = self._make_summary(
            ["google-analytics.com", "www.google-analytics.com"],
        )
        section, _ = build_deterministic_tracking_section(summary)
        # Both domains should be under one tracker entry.
        ga_entries = [e for e in section.analytics if "google-analytics.com" in e.domains]
        assert len(ga_entries) == 1
        assert len(ga_entries[0].domains) == 2

    def test_empty_input(self) -> None:
        """No domains produces an empty section."""
        summary = self._make_summary([])
        section, unclassified = build_deterministic_tracking_section(summary)
        assert unclassified == []
        assert section.analytics == []
        assert section.advertising == []
        assert section.social_media == []
        assert section.identity_resolution == []
        assert section.other == []


# ── merge_tracking_sections ────────────────────────────────────


class TestMergeTrackingSections:
    """Merge deterministic and LLM-generated sections."""

    @staticmethod
    def _entry(
        name: str,
        domains: list[str],
        purpose: str = "test",
    ) -> report.TrackerEntry:
        """Build a minimal TrackerEntry."""
        return report.TrackerEntry(
            name=name,
            domains=domains,
            purpose=purpose,
        )

    def test_llm_none_returns_deterministic(self) -> None:
        """When LLM section is None, deterministic is returned."""
        det = report.TrackingTechnologiesSection(
            analytics=[self._entry("GA", ["ga.com"])],
        )
        result = merge_tracking_sections(det, None)
        assert result is det

    def test_llm_adds_new_domains(self) -> None:
        """LLM entries with new domains are added."""
        det = report.TrackingTechnologiesSection(
            analytics=[self._entry("GA", ["ga.com"])],
        )
        llm = report.TrackingTechnologiesSection(
            advertising=[
                self._entry("NewAd", ["newad.com"]),
            ],
        )
        result = merge_tracking_sections(det, llm)
        assert len(result.advertising) == 1
        assert result.advertising[0].name == "NewAd"

    def test_llm_duplicate_domains_skipped(self) -> None:
        """LLM entries for already-classified domains are skipped."""
        det = report.TrackingTechnologiesSection(
            analytics=[self._entry("GA", ["ga.com"])],
        )
        llm = report.TrackingTechnologiesSection(
            analytics=[
                self._entry("Google Analytics", ["ga.com"]),
            ],
        )
        result = merge_tracking_sections(det, llm)
        # Should still have just one entry, not two.
        assert len(result.analytics) == 1
        assert result.analytics[0].name == "GA"

    def test_llm_partial_overlap(self) -> None:
        """LLM entry with mix of known/new domains adds new."""
        det = report.TrackingTechnologiesSection(
            advertising=[
                self._entry("Google", ["doubleclick.net"]),
            ],
        )
        llm = report.TrackingTechnologiesSection(
            advertising=[
                self._entry(
                    "Google Ads",
                    ["doubleclick.net", "googleads.com"],
                ),
            ],
        )
        result = merge_tracking_sections(det, llm)
        assert len(result.advertising) == 2
        new_entry = result.advertising[1]
        assert new_entry.domains == ["googleads.com"]

    def test_both_empty(self) -> None:
        """Two empty sections merge to empty."""
        det = report.TrackingTechnologiesSection()
        llm = report.TrackingTechnologiesSection()
        result = merge_tracking_sections(det, llm)
        assert result.analytics == []
        assert result.advertising == []
