"""Tests for src.utils.text — text processing utilities."""

from __future__ import annotations

import pytest

from src.utils.text import sanitize_domain, strip_ansi


class TestStripAnsi:
    """Tests for strip_ansi()."""

    def test_no_ansi(self) -> None:
        assert strip_ansi("hello world") == "hello world"

    def test_colour_codes(self) -> None:
        assert strip_ansi("\033[31mred\033[0m") == "red"

    def test_multi_codes(self) -> None:
        assert strip_ansi("\033[1m\033[36mbold cyan\033[0m") == "bold cyan"

    def test_empty_string(self) -> None:
        assert strip_ansi("") == ""

    def test_only_ansi(self) -> None:
        assert strip_ansi("\033[0m") == ""

    def test_mixed_content(self) -> None:
        result = strip_ansi("prefix \033[32mgreen\033[0m suffix")
        assert result == "prefix green suffix"

    def test_semi_separated_codes(self) -> None:
        assert strip_ansi("\033[1;31mbold red\033[0m") == "bold red"


class TestSanitizeDomain:
    """Tests for sanitize_domain()."""

    def test_simple_domain(self) -> None:
        assert sanitize_domain("example.com") == "example.com"

    def test_strips_www(self) -> None:
        assert sanitize_domain("www.example.com") == "example.com"

    def test_co_uk_domain(self) -> None:
        assert sanitize_domain("www.example.co.uk") == "example.co.uk"

    def test_special_characters_replaced(self) -> None:
        result = sanitize_domain("ex@mple:com/path")
        assert "@" not in result
        assert ":" not in result
        assert "/" not in result
        assert "_" in result

    def test_keeps_dots_and_hyphens(self) -> None:
        assert sanitize_domain("sub-domain.example.com") == "sub-domain.example.com"

    def test_truncation(self) -> None:
        long_domain = "a" * 100 + ".com"
        result = sanitize_domain(long_domain)
        assert len(result) <= 50

    def test_custom_max_length(self) -> None:
        result = sanitize_domain("example.com", max_length=7)
        assert len(result) <= 7

    def test_empty_string(self) -> None:
        assert sanitize_domain("") == ""

    def test_www_only(self) -> None:
        assert sanitize_domain("www.") == ""

    @pytest.mark.parametrize(
        ("domain", "expected"),
        [
            ("example.com", "example.com"),
            ("www.example.com", "example.com"),
            ("sub.example.com", "sub.example.com"),
        ],
    )
    def test_various_domains(self, domain: str, expected: str) -> None:
        assert sanitize_domain(domain) == expected
