"""Tests for src.utils.url — URL and domain extraction utilities."""

from __future__ import annotations

import pytest

from src.utils.url import extract_domain, get_base_domain, is_third_party

# ── extract_domain ──────────────────────────────────────────────


class TestExtractDomain:
    """Tests for extract_domain()."""

    def test_simple_url(self) -> None:
        assert extract_domain("https://example.com/path") == "example.com"

    def test_url_with_port(self) -> None:
        assert extract_domain("https://example.com:8080/path") == "example.com"

    def test_url_with_subdomain(self) -> None:
        assert extract_domain("https://www.example.com/path") == "www.example.com"

    def test_url_with_www(self) -> None:
        assert extract_domain("https://www.example.co.uk/path") == "www.example.co.uk"

    def test_invalid_url_returns_unknown(self) -> None:
        assert extract_domain("not a url") == "unknown"

    def test_empty_string_returns_unknown(self) -> None:
        assert extract_domain("") == "unknown"

    def test_url_without_scheme(self) -> None:
        # urlparse without scheme treats the whole thing as path
        assert extract_domain("example.com") == "unknown"

    def test_http_scheme(self) -> None:
        assert extract_domain("http://example.com") == "example.com"

    def test_deeply_nested_subdomain(self) -> None:
        assert extract_domain("https://a.b.c.example.com") == "a.b.c.example.com"


# ── get_base_domain ─────────────────────────────────────────────


class TestGetBaseDomain:
    """Tests for get_base_domain()."""

    def test_simple_domain(self) -> None:
        assert get_base_domain("example.com") == "example.com"

    def test_strips_www(self) -> None:
        assert get_base_domain("www.example.com") == "example.com"

    def test_subdomain(self) -> None:
        assert get_base_domain("sub.example.com") == "example.com"

    def test_co_uk_tld(self) -> None:
        assert get_base_domain("www.example.co.uk") == "example.co.uk"

    def test_co_uk_subdomain(self) -> None:
        assert get_base_domain("sub.example.co.uk") == "example.co.uk"

    def test_com_au_tld(self) -> None:
        assert get_base_domain("www.example.com.au") == "example.com.au"

    def test_lowercases(self) -> None:
        assert get_base_domain("WWW.EXAMPLE.COM") == "example.com"

    def test_single_label(self) -> None:
        assert get_base_domain("localhost") == "localhost"

    @pytest.mark.parametrize(
        ("domain", "expected"),
        [
            ("co.uk", "co.uk"),
            ("example.co.uk", "example.co.uk"),
            ("deep.sub.example.co.uk", "example.co.uk"),
        ],
    )
    def test_multi_part_tlds(self, domain: str, expected: str) -> None:
        assert get_base_domain(domain) == expected


# ── is_third_party ──────────────────────────────────────────────


class TestIsThirdParty:
    """Tests for is_third_party()."""

    def test_same_domain(self) -> None:
        assert is_third_party("https://example.com/script.js", "https://example.com/page") is False

    def test_subdomain_same_base(self) -> None:
        assert is_third_party("https://cdn.example.com/script.js", "https://www.example.com/page") is False

    def test_different_domain(self) -> None:
        assert is_third_party("https://tracker.com/pixel", "https://example.com/page") is True

    def test_co_uk_same_base(self) -> None:
        assert is_third_party("https://cdn.bbc.co.uk/script.js", "https://www.bbc.co.uk/") is False

    def test_empty_urls_are_same_party(self) -> None:
        assert is_third_party("", "") is False
