"""Tests for src.browser.access_detection — blocked page patterns."""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest

from src.browser.access_detection import (
    BLOCKED_BODY_PATTERNS,
    BLOCKED_TITLE_PATTERNS,
    check_for_access_denied,
)


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
            assert matches == [], f"Title {title!r} falsely matched patterns: {matches}"


class TestBlockedBodyPatterns:
    def test_non_empty(self) -> None:
        assert len(BLOCKED_BODY_PATTERNS) > 0

    def test_all_lowercase(self) -> None:
        for p in BLOCKED_BODY_PATTERNS:
            assert p == p.lower(), f"Pattern should be lowercase: {p!r}"

    def test_common_patterns_present(self) -> None:
        for expected in ("access denied", "verify you are human", "bot traffic"):
            assert expected in BLOCKED_BODY_PATTERNS, f"Missing {expected!r}"


class TestCheckForAccessDeniedTimeout:
    """Validates timeout protection in check_for_access_denied."""

    @pytest.mark.asyncio()
    async def test_returns_no_denial_on_title_timeout(self) -> None:
        """A hung page.title() must not block; assume no denial."""

        async def hang() -> str:
            await asyncio.sleep(3600)
            return "ok"

        page = mock.AsyncMock()
        page.title = hang

        result = await asyncio.wait_for(
            check_for_access_denied(page),
            timeout=15,
        )
        assert result.denied is False

    @pytest.mark.asyncio()
    async def test_returns_no_denial_on_evaluate_timeout(self) -> None:
        """A hung page.evaluate() must not block; assume no denial."""

        async def hang(*_args: object, **_kwargs: object) -> str:
            await asyncio.sleep(3600)
            return ""

        page = mock.AsyncMock()
        page.title.return_value = "My Normal Page"
        page.evaluate = hang

        result = await asyncio.wait_for(
            check_for_access_denied(page),
            timeout=15,
        )
        assert result.denied is False

    @pytest.mark.asyncio()
    async def test_detects_blocked_title(self) -> None:
        """A blocked page title is detected normally."""
        page = mock.AsyncMock()
        page.title.return_value = "Access Denied"

        result = await check_for_access_denied(page)
        assert result.denied is True
        assert "title" in (result.reason or "").lower()

    @pytest.mark.asyncio()
    async def test_detects_blocked_body(self) -> None:
        """Blocked body text is detected normally."""
        page = mock.AsyncMock()
        page.title.return_value = "Some Page"
        page.evaluate.return_value = "you have been blocked from accessing this page"

        result = await check_for_access_denied(page)
        assert result.denied is True
        assert "content" in (result.reason or "").lower()
