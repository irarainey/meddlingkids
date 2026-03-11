"""Tests for src.data.geo_loader — IP geolocation database."""

from __future__ import annotations

import textwrap
from unittest import mock

import pytest

from src.data import geo_loader


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Clear the cached database between tests."""
    geo_loader._load_database.cache_clear()


class TestLookupCountry:
    """IP-to-country binary search lookups."""

    def test_returns_none_when_db_missing(self) -> None:
        """Gracefully returns None when no database is present."""
        with mock.patch.object(geo_loader, "_load_database", return_value=None):
            assert geo_loader.lookup_country("1.2.3.4") is None

    def test_finds_country_exact_start(self) -> None:
        """Matches an IP at the exact start of a range."""
        db = ([0, 256], [255, 511], ["US", "DE"])
        with mock.patch.object(geo_loader, "_load_database", return_value=db):
            assert geo_loader.lookup_country("0.0.1.0") == "DE"

    def test_finds_country_exact_end(self) -> None:
        """Matches an IP at the exact end of a range."""
        db = ([0, 256], [255, 511], ["US", "DE"])
        with mock.patch.object(geo_loader, "_load_database", return_value=db):
            assert geo_loader.lookup_country("0.0.0.255") == "US"

    def test_finds_country_mid_range(self) -> None:
        """Matches an IP in the middle of a range."""
        # 1.0.0.0 = 16777216, 1.0.0.255 = 16777471
        db = ([16777216], [16777471], ["AU"])
        with mock.patch.object(geo_loader, "_load_database", return_value=db):
            assert geo_loader.lookup_country("1.0.0.128") == "AU"

    def test_returns_none_for_gap(self) -> None:
        """Returns None for IPs not covered by any range."""
        # Range 0-10, then 100-200 — gap at 50
        db = ([0, 100], [10, 200], ["US", "DE"])
        with mock.patch.object(geo_loader, "_load_database", return_value=db):
            assert geo_loader.lookup_country("0.0.0.50") is None

    def test_invalid_ip_returns_none(self) -> None:
        """Returns None for malformed IP strings."""
        db = ([0], [255], ["US"])
        with mock.patch.object(geo_loader, "_load_database", return_value=db):
            assert geo_loader.lookup_country("not-an-ip") is None

    def test_ipv6_lookup(self) -> None:
        """Supports IPv6 addresses when the database has IPv6 ranges."""
        # ::1 = 1 as integer
        db = ([0, 2], [1, 10], ["LO", "DE"])
        with mock.patch.object(geo_loader, "_load_database", return_value=db):
            assert geo_loader.lookup_country("::1") == "LO"


class TestIsAvailable:
    """Database availability checks."""

    def test_available_when_loaded(self) -> None:
        db = ([0], [255], ["US"])
        with mock.patch.object(geo_loader, "_load_database", return_value=db):
            assert geo_loader.is_available() is True

    def test_unavailable_when_missing(self) -> None:
        with mock.patch.object(geo_loader, "_load_database", return_value=None):
            assert geo_loader.is_available() is False


class TestLoadDatabase:
    """CSV parsing and validation."""

    def test_parses_valid_csv(self, tmp_path: object) -> None:
        """Parses a well-formed DB-IP Lite CSV."""
        import pathlib

        csv_content = textwrap.dedent("""\
            1.0.0.0,1.0.0.255,AU
            1.0.1.0,1.0.3.255,CN
            2001:200::,2001:200:ffff:ffff:ffff:ffff:ffff:ffff,JP
        """)
        geo_dir = pathlib.Path(str(tmp_path)) / "geo"
        geo_dir.mkdir()
        csv_file = geo_dir / "dbip-country-lite.csv"
        csv_file.write_text(csv_content)

        with mock.patch.object(geo_loader, "_GEO_DIR", geo_dir):
            result = geo_loader._load_database.__wrapped__()

        assert result is not None
        starts, _ends, countries = result
        assert len(starts) == 3
        assert countries[0] == "AU"
        assert countries[1] == "CN"
        assert countries[2] == "JP"

    def test_skips_malformed_rows(self, tmp_path: object) -> None:
        """Silently skips rows with invalid IP addresses."""
        import pathlib

        csv_content = textwrap.dedent("""\
            1.0.0.0,1.0.0.255,AU
            bad-ip,1.0.3.255,CN
            1.0.4.0,1.0.4.255,DE
        """)
        geo_dir = pathlib.Path(str(tmp_path)) / "geo"
        geo_dir.mkdir()
        csv_file = geo_dir / "dbip-country-lite.csv"
        csv_file.write_text(csv_content)

        with mock.patch.object(geo_loader, "_GEO_DIR", geo_dir):
            result = geo_loader._load_database.__wrapped__()

        assert result is not None
        _, _, countries = result
        assert len(countries) == 2
        assert countries == ["AU", "DE"]

    def test_returns_none_when_file_missing(self) -> None:
        """Returns None when no CSV file exists."""
        import pathlib

        with mock.patch.object(
            geo_loader,
            "_GEO_DIR",
            pathlib.Path("/nonexistent"),
        ):
            result = geo_loader._load_database.__wrapped__()

        assert result is None
