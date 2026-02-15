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
        for expected in ("access denied", "forbidden", "captcha", "cloudflare"):
            assert expected in BLOCKED_TITLE_PATTERNS, f"Missing {expected!r}"


class TestBlockedBodyPatterns:
    def test_non_empty(self) -> None:
        assert len(BLOCKED_BODY_PATTERNS) > 0

    def test_all_lowercase(self) -> None:
        for p in BLOCKED_BODY_PATTERNS:
            assert p == p.lower(), f"Pattern should be lowercase: {p!r}"

    def test_common_patterns_present(self) -> None:
        for expected in ("access denied", "verify you are human", "bot traffic"):
            assert expected in BLOCKED_BODY_PATTERNS, f"Missing {expected!r}"
