"""Tests for src.consent.text_parser — local consent text parsing."""

from __future__ import annotations

import pytest

from src.consent import text_parser

# ── Consent-context gate ────────────────────────────────────────


class TestConsentContextGate:
    """Tests for _CONSENT_CONTEXT_RE gate regex."""

    @pytest.mark.parametrize(
        "text",
        [
            "We use cookies to improve your experience.",
            "Cookie consent settings",
            "Manage my cookie preferences",
            "Accept all cookies",
            "Reject all cookies",
            "This site uses cookies",
            "Data processing purposes",
            "Legitimate interest",
            "IAB Europe Transparency & Consent Framework",
            "GDPR privacy compliance",
            "Consent manage dialog",
        ],
        ids=[
            "we-use-cookies",
            "cookie-consent",
            "manage-cookie-prefs",
            "accept-all",
            "reject-all",
            "site-uses-cookies",
            "data-processing",
            "legitimate-interest",
            "iab-europe",
            "gdpr",
            "consent-manage",
        ],
    )
    def test_original_patterns_match(self, text: str) -> None:
        assert text_parser._CONSENT_CONTEXT_RE.search(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Quantcast Choice consent platform",
            "Sourcepoint CMP",
            "OneTrust cookie banner",
            "Cookiebot consent manager",
            "Didomi privacy widget",
            "Google Funding Choices",
            "Privacy Manager",
            "Privacy Center",
            "Privacy Notice",
        ],
        ids=[
            "quantcast",
            "sourcepoint",
            "onetrust",
            "cookiebot",
            "didomi",
            "funding-choices",
            "privacy-manager",
            "privacy-center",
            "privacy-notice",
        ],
    )
    def test_cmp_specific_patterns_match(self, text: str) -> None:
        assert text_parser._CONSENT_CONTEXT_RE.search(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Store and/or access information on a device",
            "Select basic ads for display",
            "Create a personalised ads profile based on browsing",
            "Create personalized content profile",
            "Measure ad performance and attribution",
            "Measure advertising performance",
            "Measure content performance",
            "Understand audiences through statistics",
            "Develop and improve products",
            "Use limited data to select advertising",
            "Use limited data to select content",
        ],
        ids=[
            "store-access",
            "select-basic-ads",
            "personalised-ads-profile",
            "personalized-content",
            "measure-ad-perf",
            "measure-advertising",
            "measure-content",
            "understand-audiences",
            "develop-improve",
            "limited-data-ads",
            "limited-data-content",
        ],
    )
    def test_tcf_purpose_phrases_match(self, text: str) -> None:
        assert text_parser._CONSENT_CONTEXT_RE.search(text)

    @pytest.mark.parametrize(
        "text",
        [
            "We and our 842 partners need your consent",
            "Our 150+ partners use cookies",
            "53 vendors on this site",
            "View our partner list",
            "Vendor list",
        ],
        ids=[
            "our-842-partners",
            "150-plus-partners",
            "53-vendors",
            "partner-list",
            "vendor-list",
        ],
    )
    def test_vendor_partner_indicators_match(self, text: str) -> None:
        assert text_parser._CONSENT_CONTEXT_RE.search(text)

    def test_plain_news_article_does_not_match(self) -> None:
        text = (
            "Labour leads in the polls ahead of the general election. "
            "The Prime Minister addressed the nation last night."
        )
        assert text_parser._CONSENT_CONTEXT_RE.search(text) is None

    def test_navigation_text_does_not_match(self) -> None:
        text = "Home News Sport Business Opinion Arts Travel"
        assert text_parser._CONSENT_CONTEXT_RE.search(text) is None

    def test_quantcast_choice_dialog_text(self) -> None:
        """Regression: Quantcast Choice consent text was previously
        rejected by the gate because it didn't contain any of the
        original trigger phrases."""
        text = (
            "We and our 842 partners need your consent to store "
            "and/or access information on a device for the purposes "
            "listed below. You may click to consent to our processing. "
            "Alternatively you may access more detailed information "
            "and change your preferences before consenting."
        )
        assert text_parser._CONSENT_CONTEXT_RE.search(text)

    def test_bbc_short_dialog_text(self) -> None:
        """Regression: BBC short consent dialog should match via
        'cookie' keyword patterns."""
        text = "Let us know you agree to cookies"
        assert text_parser._CONSENT_CONTEXT_RE.search(text)


# ── Purpose extraction ──────────────────────────────────────────


class TestPurposeExtraction:
    def test_extracts_tcf_purposes(self) -> None:
        text = (
            "Store and/or access information on a device. "
            "Use limited data to select advertising. "
            "Measure advertising performance. "
            "Understand audiences through statistics. "
            "Develop and improve products."
        )
        purposes = text_parser._extract_purposes(text)
        assert len(purposes) == 5

    def test_deduplicates_purposes(self) -> None:
        text = (
            "Measure advertising performance. "
            "Measure advertising performance."
        )
        purposes = text_parser._extract_purposes(text)
        assert len(purposes) == 1

    def test_empty_text_returns_empty(self) -> None:
        assert text_parser._extract_purposes("") == []


# ── Category extraction ─────────────────────────────────────────


class TestCategoryExtraction:
    def test_extracts_known_categories(self) -> None:
        text = (
            "Strictly necessary cookies are essential. "
            "Performance cookies help us measure. "
            "Analytics cookies track usage. "
            "Targeting cookies for ads."
        )
        categories = text_parser._extract_categories(text)
        names = [c.name for c in categories]
        assert "Strictly Necessary" in names
        assert "Performance" in names
        assert "Analytics" in names
        assert "Targeting / Advertising" in names

    def test_necessary_category_marked_required(self) -> None:
        text = "Strictly necessary cookies to operate."
        categories = text_parser._extract_categories(text)
        assert categories[0].required is True


# ── Full parse ──────────────────────────────────────────────────


class TestParseConsentText:
    def test_returns_empty_for_non_consent_text(self) -> None:
        result = text_parser.parse_consent_text("Just some news article text about politics.")
        assert result.purposes == []
        assert result.categories == []

    def test_extracts_purposes_and_categories(self) -> None:
        text = (
            "Cookie consent preferences. "
            "We use the following cookies: "
            "Strictly necessary cookies, "
            "Performance cookies, "
            "Store and/or access information on a device. "
            "Measure advertising performance."
        )
        result = text_parser.parse_consent_text(text)
        assert len(result.purposes) >= 2
        assert len(result.categories) >= 2

    def test_extracts_partner_count(self) -> None:
        text = "We and our 842 partners use cookies."
        result = text_parser.parse_consent_text(text)
        assert result.claimed_partner_count == 842

    def test_partner_count_extracted_even_when_gate_fails(self) -> None:
        """Partner count extraction works even without full consent context."""
        text = "We and our 200 partners process data."
        result = text_parser.parse_consent_text(text)
        assert result.claimed_partner_count == 200

    def test_detects_manage_options(self) -> None:
        text = "Cookie consent. Manage my preferences. Accept all cookies."
        result = text_parser.parse_consent_text(text)
        assert result.has_manage_options is True
