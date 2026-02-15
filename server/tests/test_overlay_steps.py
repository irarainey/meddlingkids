"""Tests for src.pipeline.overlay_steps — overlay message helper."""

from __future__ import annotations

import pytest

from src.pipeline.overlay_steps import get_overlay_message


class TestGetOverlayMessage:
    @pytest.mark.parametrize(
        ("overlay_type", "expected"),
        [
            ("cookie-consent", "Cookie consent detected"),
            ("sign-in", "Sign-in prompt detected"),
            ("newsletter", "Newsletter popup detected"),
            ("paywall", "Paywall detected"),
            ("age-verification", "Age verification detected"),
        ],
    )
    def test_known_types(self, overlay_type: str, expected: str) -> None:
        assert get_overlay_message(overlay_type) == expected

    def test_unknown_type(self) -> None:
        assert get_overlay_message("something-else") == "Overlay detected"

    def test_none_type(self) -> None:
        assert get_overlay_message(None) == "Overlay detected"
