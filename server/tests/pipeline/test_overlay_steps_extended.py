"""Extended tests for src.pipeline.overlay_steps — helper functions."""

from __future__ import annotations

from src.pipeline.overlay_steps import get_overlay_message


class TestGetOverlayMessageExtended:
    """Extended tests for get_overlay_message()."""

    def test_cookie_consent(self) -> None:
        assert get_overlay_message("cookie-consent") == "Cookie consent detected"

    def test_sign_in(self) -> None:
        assert get_overlay_message("sign-in") == "Sign-in prompt detected"

    def test_newsletter(self) -> None:
        assert get_overlay_message("newsletter") == "Newsletter popup detected"

    def test_paywall(self) -> None:
        assert get_overlay_message("paywall") == "Paywall detected"

    def test_age_verification(self) -> None:
        assert get_overlay_message("age-verification") == "Age verification detected"

    def test_unknown_type(self) -> None:
        assert get_overlay_message("unknown") == "Overlay detected"

    def test_none_type(self) -> None:
        assert get_overlay_message(None) == "Overlay detected"

    def test_empty_string(self) -> None:
        assert get_overlay_message("") == "Overlay detected"
