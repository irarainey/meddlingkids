"""Tests for the shared GDPR/TCF context builder."""

from __future__ import annotations

from src.agents import gdpr_context


class TestBuildGdprReference:
    """Tests for build_gdpr_reference."""

    def test_returns_string(self) -> None:
        result = gdpr_context.build_gdpr_reference()
        assert isinstance(result, str)

    def test_default_heading(self) -> None:
        result = gdpr_context.build_gdpr_reference()
        assert result.startswith("## GDPR / TCF Reference")

    def test_custom_heading(self) -> None:
        result = gdpr_context.build_gdpr_reference(heading="## Custom Heading")
        assert result.startswith("## Custom Heading")

    def test_contains_tcf_purposes(self) -> None:
        result = gdpr_context.build_gdpr_reference()
        assert "IAB TCF" in result
        assert "Purpose" in result

    def test_contains_consent_cookies(self) -> None:
        result = gdpr_context.build_gdpr_reference()
        assert "Consent-State Cookies" in result or "consent" in result.lower()

    def test_contains_gdpr_lawful_bases(self) -> None:
        result = gdpr_context.build_gdpr_reference()
        assert "Lawful Bases" in result or "lawful" in result.lower()

    def test_contains_eprivacy_categories(self) -> None:
        result = gdpr_context.build_gdpr_reference()
        assert "ePrivacy" in result or "Cookie Categories" in result
