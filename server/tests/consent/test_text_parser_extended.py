"""Tests for src.consent.text_parser — purpose/partner extraction."""

from __future__ import annotations

from src.consent.text_parser import (
    _extract_partner_count,
    _extract_partners,
    _extract_purposes,
    parse_consent_text,
)


class TestExtractPurposes:
    """Tests for _extract_purposes() — IAB TCF purpose extraction."""

    def test_purpose_1(self) -> None:
        text = "Store and/or access information on a device"
        purposes = _extract_purposes(text)
        assert any("Store" in p for p in purposes)

    def test_purpose_2(self) -> None:
        text = "Use limited data to select advertising"
        purposes = _extract_purposes(text)
        assert any("advertising" in p for p in purposes)

    def test_purpose_7(self) -> None:
        text = "Measure advertising performance"
        purposes = _extract_purposes(text)
        assert any("Measure advertising" in p for p in purposes)

    def test_purpose_8(self) -> None:
        text = "Measure content performance"
        purposes = _extract_purposes(text)
        assert any("Measure content" in p for p in purposes)

    def test_purpose_9(self) -> None:
        text = "Understand audiences through statistics"
        purposes = _extract_purposes(text)
        assert any("audiences" in p for p in purposes)

    def test_purpose_10(self) -> None:
        text = "Develop and improve products"
        purposes = _extract_purposes(text)
        assert any("Develop" in p for p in purposes)

    def test_purpose_11(self) -> None:
        text = "Use limited data to select content"
        purposes = _extract_purposes(text)
        assert any("content" in p for p in purposes)

    def test_special_feature_geolocation(self) -> None:
        text = "Use precise geolocation data"
        purposes = _extract_purposes(text)
        assert any("geolocation" in p for p in purposes)

    def test_special_feature_device_scan(self) -> None:
        text = "Actively scan device characteristics for identification"
        purposes = _extract_purposes(text)
        assert any("scan" in p for p in purposes)

    def test_no_purposes(self) -> None:
        text = "Just a regular page about cooking recipes."
        purposes = _extract_purposes(text)
        assert purposes == []

    def test_numbered_purpose_reference(self) -> None:
        text = "We use purposes: Purpose 1, Purpose 3, Purpose 7."
        purposes = _extract_purposes(text)
        assert len(purposes) >= 2

    def test_deduplication(self) -> None:
        text = "Store and/or access information on a device. Store and/or access information on a device."
        purposes = _extract_purposes(text)
        store_purposes = [p for p in purposes if "Store" in p]
        assert len(store_purposes) == 1


class TestExtractPartners:
    """Tests for _extract_partners() — partner name extraction."""

    def test_partner_list_block(self) -> None:
        text = "--- partner list details ---\nPARTNER LIST:\nGoogle LLC\nFacebook Inc\nAdobe Systems\n"
        partners = _extract_partners(text)
        names = [p.name for p in partners]
        assert "Google LLC" in names
        assert "Facebook Inc" in names
        assert "Adobe Systems" in names

    def test_no_partner_section(self) -> None:
        text = "This is a regular page with no partner information."
        partners = _extract_partners(text)
        assert partners == []

    def test_excludes_boilerplate(self) -> None:
        text = "--- partner list ---\nPARTNER LIST:\naccept\nreject\nGoogle LLC\nprivacy policy\n"
        partners = _extract_partners(text)
        names = [p.name for p in partners]
        assert "accept" not in names
        assert "privacy policy" not in names

    def test_excludes_short_names(self) -> None:
        text = "--- vendor details ---\nPARTNER LIST:\nAB\nGoogle LLC\n"
        partners = _extract_partners(text)
        names = [p.name for p in partners]
        assert "AB" not in names

    def test_deduplication(self) -> None:
        text = "--- partner list ---\nPARTNER LIST:\nGoogle LLC\nGoogle LLC\n"
        partners = _extract_partners(text)
        names = [p.name for p in partners]
        assert names.count("Google LLC") == 1


class TestExtractPartnerCount:
    """Tests for _extract_partner_count()."""

    def test_partners_count(self) -> None:
        text = "We and our 250 partners use cookies"
        count = _extract_partner_count(text)
        assert count == 250

    def test_partners_with_plus(self) -> None:
        text = "Our 100+ partners help deliver ads"
        count = _extract_partner_count(text)
        assert count == 100

    def test_vendors_count(self) -> None:
        text = "897 vendors are listed"
        count = _extract_partner_count(text)
        assert count == 897

    def test_sharing_with_phrase(self) -> None:
        text = "We are sharing data with 50 partners"
        count = _extract_partner_count(text)
        assert count == 50

    def test_no_count(self) -> None:
        text = "We use cookies for a better experience."
        count = _extract_partner_count(text)
        assert count is None

    def test_small_numbers_excluded(self) -> None:
        text = "Our 3 partners"
        count = _extract_partner_count(text)
        assert count is None

    def test_comma_separated_numbers(self) -> None:
        text = "We and our 1,234 partners"
        count = _extract_partner_count(text)
        assert count == 1234

    def test_max_of_multiple(self) -> None:
        text = "100 partners, 200 vendors"
        count = _extract_partner_count(text)
        assert count == 200


class TestParseConsentText:
    """Tests for parse_consent_text() — the top-level parser."""

    def test_no_consent_context(self) -> None:
        text = "A regular news article about technology."
        result = parse_consent_text(text)
        assert result.categories == []
        assert result.purposes == []
        assert result.partners == []

    def test_with_consent_context(self) -> None:
        text = (
            "This site uses cookies. We use cookies to improve your experience. "
            "You can manage my preferences. "
            "Strictly necessary cookies are required. "
            "Analytics cookies help us understand usage. "
            "Store and/or access information on a device."
        )
        result = parse_consent_text(text)
        assert len(result.categories) >= 1
        assert result.has_manage_options is True

    def test_manages_options_detected(self) -> None:
        text = "We use cookies. Manage my preferences."
        result = parse_consent_text(text)
        assert result.has_manage_options is True

    def test_partner_count_even_without_context(self) -> None:
        text = "We and our 150 partners help deliver content."
        result = parse_consent_text(text)
        assert result.claimed_partner_count == 150

    def test_raw_text_truncated(self) -> None:
        long_text = "We use cookies. " + "x" * 10000
        result = parse_consent_text(long_text)
        assert len(result.raw_text) <= 5000
