"""Tests for src.browser.access_detection — blocked page patterns."""

from __future__ import annotations

from src.browser.access_detection import BLOCKED_BODY_PATTERNS, BLOCKED_TITLE_PATTERNS


class TestBlockedTitlePatterns:
    def test_non_empty(self) -> None:
        assert len(BLOCKED_TITLE_PATTERNS) > 0

    def test_all_lowercase(self) -> None:
        for p in BLOCKED_TITLE_PATTERNS:
            assert p == p.lower(), f"Pattern should be lowercase: {p!r}"

    def test_common_patterns_present(self) -> None:
        for expected in ("access denied", "403 forbidden", "captcha", "cloudflare"):
            assert expected in BLOCKED_TITLE_PATTERNS, f"Missing {expected!r}"


    def test_no_false_positive_on_content_words(self) -> None:
        """Legitimate article titles must not trigger blocking."""
        safe_titles = [
            "Delivery robots take to the streets of Bristol",
            "Robot vacuum cleaners reviewed",
            "The 403 best restaurants in London",
            "Blocked drains cause flooding in city centre",
        ]
        for title in safe_titles:
            title_lower = title.lower()
            matches = [p for p in BLOCKED_TITLE_PATTERNS if p in title_lower]
            assert matches == [], (
                f"Title {title!r} falsely matched patterns: {matches}"
            )


class TestBlockedBodyPatterns:
    def test_non_empty(self) -> None:
        assert len(BLOCKED_BODY_PATTERNS) > 0

    def test_all_lowercase(self) -> None:
        for p in BLOCKED_BODY_PATTERNS:
            assert p == p.lower(), f"Pattern should be lowercase: {p!r}"

    def test_common_patterns_present(self) -> None:
        for expected in ("access denied", "verify you are human", "bot traffic"):
            assert expected in BLOCKED_BODY_PATTERNS, f"Missing {expected!r}"
