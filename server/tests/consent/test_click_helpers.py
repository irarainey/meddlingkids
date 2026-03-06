"""Tests for src.consent.click — pure function tests for click helpers."""

from __future__ import annotations

import pytest

from src.consent.click import ClickResult, _parse_selector


class TestClickResult:
    """Tests for the ClickResult dataclass."""

    def test_default_failure(self) -> None:
        result = ClickResult(success=False)
        assert result.success is False
        assert result.strategy is None
        assert result.frame_type is None

    def test_success_with_strategy(self) -> None:
        result = ClickResult(success=True, strategy="role-button", frame_type="main")
        assert result.success is True
        assert result.strategy == "role-button"
        assert result.frame_type == "main"

    def test_consent_iframe_type(self) -> None:
        result = ClickResult(success=True, strategy="css", frame_type="consent-iframe")
        assert result.frame_type == "consent-iframe"

    def test_frozen(self) -> None:
        result = ClickResult(success=True)
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]


class TestParseSelector:
    """Tests for _parse_selector() — LLM selector parsing."""

    def test_plain_css_selector(self) -> None:
        css, text = _parse_selector(".accept-btn")
        assert css == ".accept-btn"
        assert text is None

    def test_has_text_pseudo_selector(self) -> None:
        css, text = _parse_selector("button:has-text('Accept All')")
        assert css == "button"
        assert text == "Accept All"

    def test_contains_pseudo_selector(self) -> None:
        css, text = _parse_selector('div:contains("Allow cookies")')
        assert css == "div"
        assert text == "Allow cookies"

    def test_has_text_no_css_prefix(self) -> None:
        css, text = _parse_selector(":has-text('OK')")
        assert css is None
        assert text == "OK"

    def test_complex_css_with_pseudo(self) -> None:
        css, text = _parse_selector('#consent-dialog button:has-text("Accept")')
        assert css == "#consent-dialog button"
        assert text == "Accept"

    def test_no_pseudo(self) -> None:
        css, text = _parse_selector("#accept-button")
        assert css == "#accept-button"
        assert text is None

    def test_id_selector(self) -> None:
        css, text = _parse_selector("#onetrust-accept-btn-handler")
        assert css == "#onetrust-accept-btn-handler"
        assert text is None

    def test_attribute_selector(self) -> None:
        css, text = _parse_selector('[data-testid="accept"]')
        assert css == '[data-testid="accept"]'
        assert text is None
