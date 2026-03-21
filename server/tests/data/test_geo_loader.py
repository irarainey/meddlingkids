"""Tests for src.data.geo_loader — IP geolocation database."""

from __future__ import annotations

import gzip
import pathlib
import textwrap
from unittest import mock

import pytest

from src.data import geo_loader


def _write_gz_csv(
    geo_dir: pathlib.Path,
    content: str,
    name: str = "dbip-country-lite-2026-03.csv.gz",
) -> pathlib.Path:
    """Helper: write *content* as a gzipped CSV into *geo_dir*."""
    gz_path = geo_dir / name
    gz_path.write_bytes(gzip.compress(content.encode()))
    return gz_path


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Reset the module-level database cache between tests."""
    geo_loader._db_cache = None
    geo_loader._db_loaded = False


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
    """Compressed CSV parsing and validation."""

    def test_parses_valid_csv_gz(self, tmp_path: object) -> None:
        """Parses a well-formed gzipped DB-IP Lite CSV."""
        csv_content = textwrap.dedent("""\
            1.0.0.0,1.0.0.255,AU
            1.0.1.0,1.0.3.255,CN
            2001:200::,2001:200:ffff:ffff:ffff:ffff:ffff:ffff,JP
        """)
        geo_dir = pathlib.Path(str(tmp_path)) / "geo"
        geo_dir.mkdir()
        _write_gz_csv(geo_dir, csv_content)

        with mock.patch.object(geo_loader, "_GEO_DIR", geo_dir):
            result = geo_loader._load_database()

        assert result is not None
        starts, _ends, countries = result
        assert len(starts) == 3
        assert countries[0] == "AU"
        assert countries[1] == "CN"
        assert countries[2] == "JP"

    def test_skips_malformed_rows(self, tmp_path: object) -> None:
        """Silently skips rows with invalid IP addresses."""
        csv_content = textwrap.dedent("""\
            1.0.0.0,1.0.0.255,AU
            bad-ip,1.0.3.255,CN
            1.0.4.0,1.0.4.255,DE
        """)
        geo_dir = pathlib.Path(str(tmp_path)) / "geo"
        geo_dir.mkdir()
        _write_gz_csv(geo_dir, csv_content)

        with mock.patch.object(geo_loader, "_GEO_DIR", geo_dir):
            result = geo_loader._load_database()

        assert result is not None
        _, _, countries = result
        assert len(countries) == 2
        assert countries == ["AU", "DE"]

    def test_returns_none_when_file_missing(self) -> None:
        """Returns None when no .csv.gz file exists."""
        with mock.patch.object(
            geo_loader,
            "_GEO_DIR",
            pathlib.Path("/nonexistent"),
        ):
            result = geo_loader._load_database()

        assert result is None

    def test_picks_newest_file(self, tmp_path: object) -> None:
        """When multiple .csv.gz files exist, uses the newest."""
        old_csv = "1.0.0.0,1.0.0.255,US\n"
        new_csv = "1.0.0.0,1.0.0.255,DE\n"

        geo_dir = pathlib.Path(str(tmp_path)) / "geo"
        geo_dir.mkdir()
        _write_gz_csv(geo_dir, old_csv, "dbip-country-lite-2025-01.csv.gz")
        _write_gz_csv(geo_dir, new_csv, "dbip-country-lite-2026-03.csv.gz")

        with mock.patch.object(geo_loader, "_GEO_DIR", geo_dir):
            result = geo_loader._load_database()

        assert result is not None
        _, _, countries = result
        assert countries == ["DE"]
