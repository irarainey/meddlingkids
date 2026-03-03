"""Tests for src.utils.url — URL and domain extraction utilities."""

from __future__ import annotations

import pytest

from src.utils.url import (
    UnsafeURLError,
    extract_domain,
    get_base_domain,
    get_cname_target,
    is_third_party,
    validate_analysis_url,
)

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

    def test_cname_cloaked_domain_is_third_party(self) -> None:
        """A first-party subdomain that CNAME-aliases to a tracker
        should be classified as third-party."""
        from src.data import loader

        cname_domains = loader.get_cname_domains()
        if not cname_domains:
            pytest.skip("No CNAME data available")
        # Pick the first entry to test with
        cloaked_subdomain = next(iter(cname_domains))
        # Build a URL from the cloaked subdomain
        cloaked_url = f"https://{cloaked_subdomain}/pixel.gif"
        # The page URL uses the same parent domain
        parts = cloaked_subdomain.split(".")
        if len(parts) >= 2:
            page_domain = ".".join(parts[-2:])
        else:
            page_domain = cloaked_subdomain
        page_url = f"https://www.{page_domain}/"
        assert is_third_party(cloaked_url, page_url) is True

    def test_uncloaked_first_party_not_affected(self) -> None:
        """A normal first-party subdomain should not be
        flagged as third-party by CNAME checking."""
        assert (
            is_third_party(
                "https://cdn.example.com/style.css",
                "https://www.example.com/page",
            )
            is False
        )


class TestGetCnameTarget:
    """Tests for get_cname_target()."""

    def test_unknown_url_returns_none(self) -> None:
        assert get_cname_target("https://www.example.com/page") is None

    def test_known_cloaked_url_returns_target(self) -> None:
        from src.data import loader

        cname_domains = loader.get_cname_domains()
        if not cname_domains:
            pytest.skip("No CNAME data available")
        cloaked = next(iter(cname_domains))
        expected = cname_domains[cloaked]
        result = get_cname_target(f"https://{cloaked}/pixel")
        assert result == expected


# ── validate_analysis_url ─────────────────────────────────────────


class TestValidateAnalysisUrl:
    """Tests for SSRF prevention via validate_analysis_url()."""

    async def test_https_url_allowed(self) -> None:
        await validate_analysis_url("https://example.com")

    async def test_http_url_allowed(self) -> None:
        await validate_analysis_url("http://example.com")

    async def test_ftp_scheme_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="Only http and https"):
            await validate_analysis_url("ftp://example.com/file")

    async def test_file_scheme_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="Only http and https"):
            await validate_analysis_url("file:///etc/passwd")

    async def test_javascript_scheme_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="Only http and https"):
            await validate_analysis_url("javascript:alert(1)")

    async def test_no_hostname_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="no hostname"):
            await validate_analysis_url("http://")

    async def test_localhost_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="Blocked hostname"):
            await validate_analysis_url("http://localhost/admin")

    async def test_metadata_hostname_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="Blocked hostname"):
            await validate_analysis_url("http://metadata.google.internal/computeMetadata/v1/")

    async def test_loopback_ip_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="non-public address"):
            await validate_analysis_url("http://127.0.0.1/")

    async def test_private_ip_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="non-public address"):
            await validate_analysis_url("http://192.168.1.1/")

    async def test_link_local_ip_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="non-public address"):
            await validate_analysis_url("http://169.254.169.254/latest/meta-data/")

    async def test_private_10_range_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="non-public address"):
            await validate_analysis_url("http://10.0.0.1/")

    async def test_private_172_range_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="non-public address"):
            await validate_analysis_url("http://172.16.0.1/")

    async def test_unresolvable_hostname_allowed(self) -> None:
        # DNS failures are fine — browser will handle them
        await validate_analysis_url("https://this-domain-definitely-does-not-exist-xyz123abc.com")
