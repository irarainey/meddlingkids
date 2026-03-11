"""Tests for src.analysis.geo_lookup — DNS-based geolocation."""

from __future__ import annotations

from unittest import mock

import pytest

from src.analysis import geo_lookup


@pytest.fixture(autouse=True)
def _clear_dns_cache() -> None:
    """Clear the DNS resolution cache between tests."""
    geo_lookup._resolve_domain.cache_clear()


class TestResolveDomain:
    """DNS resolution helper."""

    def test_returns_ip_on_success(self) -> None:
        fake_result = [(2, 1, 6, "", ("93.184.216.34", 0))]
        with mock.patch("socket.getaddrinfo", return_value=fake_result):
            assert geo_lookup._resolve_domain("example.com") == "93.184.216.34"

    def test_returns_none_on_failure(self) -> None:
        import socket

        with mock.patch(
            "socket.getaddrinfo",
            side_effect=socket.gaierror("not found"),
        ):
            assert geo_lookup._resolve_domain("nonexistent.invalid") is None


class TestResolveDomainCountry:
    """Combined DNS + geolocation lookup."""

    def test_returns_country_code(self) -> None:
        with (
            mock.patch.object(
                geo_lookup,
                "_resolve_domain",
                return_value="93.184.216.34",
            ),
            mock.patch.object(
                geo_lookup.geo_loader,
                "lookup_country",
                return_value="US",
            ),
        ):
            assert geo_lookup.resolve_domain_country("example.com") == "US"

    def test_returns_none_when_dns_fails(self) -> None:
        with mock.patch.object(
            geo_lookup,
            "_resolve_domain",
            return_value=None,
        ):
            assert geo_lookup.resolve_domain_country("bad.invalid") is None

    def test_returns_none_when_geo_unavailable(self) -> None:
        with (
            mock.patch.object(
                geo_lookup,
                "_resolve_domain",
                return_value="10.0.0.1",
            ),
            mock.patch.object(
                geo_lookup.geo_loader,
                "lookup_country",
                return_value=None,
            ),
        ):
            assert geo_lookup.resolve_domain_country("internal.local") is None


class TestResolvDomainsCountries:
    """Async batch resolution."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_geo_unavailable(self) -> None:
        with mock.patch.object(
            geo_lookup.geo_loader,
            "is_available",
            return_value=False,
        ):
            result = await geo_lookup.resolve_domains_countries(
                ["example.com"],
            )
            assert result == {}

    @pytest.mark.asyncio
    async def test_resolves_multiple_domains(self) -> None:
        countries = {"a.com": "US", "b.com": "DE"}

        def fake_resolve(domain: str) -> str | None:
            return countries.get(domain)

        with (
            mock.patch.object(
                geo_lookup.geo_loader,
                "is_available",
                return_value=True,
            ),
            mock.patch.object(
                geo_lookup,
                "resolve_domain_country",
                side_effect=fake_resolve,
            ),
        ):
            result = await geo_lookup.resolve_domains_countries(
                ["a.com", "b.com", "c.com"],
            )
            assert result["a.com"] == "US"
            assert result["b.com"] == "DE"
            assert result["c.com"] is None
