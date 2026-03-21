"""IP geolocation database loader.

Loads the DB-IP Lite country database (CC BY 4.0) and
provides O(log n) IP-to-country lookups using binary search
on sorted IPv4/IPv6 integer ranges.

The database is bundled as a compressed ``.csv.gz`` file in
the ``geo/`` directory.  When absent, all lookups return
``None`` and a debug message is logged once.  Use
``scripts/update-geo-db.sh`` to refresh the bundled file.

Attribution: IP Geolocation by DB-IP (https://db-ip.com)
License: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)
"""

from __future__ import annotations

import bisect
import csv
import gzip
import io
import pathlib
import socket
import struct

from src.utils import logger

log = logger.create_logger("GeoLoader")

_GEO_DIR = pathlib.Path(__file__).resolve().parent / "geo"

# Glob pattern for the bundled compressed database.
_GZ_GLOB = "dbip-country-lite-*.csv.gz"

# Module-level cache — only populated after a successful parse.
_db_cache: tuple[list[int], list[int], list[str]] | None = None
_db_loaded: bool = False


def _find_database() -> pathlib.Path | None:
    """Locate the newest bundled ``.csv.gz`` file in the geo dir.

    Returns ``None`` when no database file is present.
    """
    geo_dir = _GEO_DIR.resolve()
    candidates = sorted(geo_dir.glob(_GZ_GLOB))
    if not candidates:
        return None
    newest = candidates[-1]
    # Prevent symlink escape outside the data directory.
    if not newest.resolve().is_relative_to(geo_dir):
        log.error(
            "Geo database file escapes data directory",
            {"path": str(newest)},
        )
        return None
    return newest


def _load_database() -> tuple[list[int], list[int], list[str]] | None:
    """Parse the bundled DB-IP Lite CSV into sorted ranges.

    Reads directly from the compressed ``.csv.gz`` to avoid
    needing to decompress to disk.  The result is cached after
    the first successful parse.

    Returns a tuple of ``(starts, ends, countries)`` where
    each list is aligned by index, or ``None`` when no
    database file is present.
    """
    global _db_cache, _db_loaded
    if _db_loaded:
        return _db_cache

    gz_path = _find_database()
    if gz_path is None:
        log.debug(
            "IP geolocation database not found — run scripts/update-geo-db.sh to download it",
        )
        return None

    starts: list[int] = []
    ends: list[int] = []
    countries: list[str] = []

    with gzip.open(gz_path, "rt", encoding="utf-8") as fh:
        reader = csv.reader(io.StringIO(fh.read()))
        for row in reader:
            if len(row) < 3:
                continue
            try:
                start_int = _ip_to_int(row[0])
                end_int = _ip_to_int(row[1])
                country = row[2].upper()
            except (ValueError, IndexError, OSError):
                continue

            starts.append(start_int)
            ends.append(end_int)
            countries.append(country)

    result = starts, ends, countries
    log.info(
        "IP geolocation database loaded",
        {
            "file": gz_path.name,
            "entries": len(starts),
        },
    )

    _db_cache = result
    _db_loaded = True
    return result


def _ip_to_int(addr: str) -> int:
    """Convert an IP address string to an integer.

    Uses ``socket.inet_pton`` for fast C-level parsing.

    Args:
        addr: IPv4 or IPv6 address string.

    Returns:
        Integer representation of the address.
    """
    if ":" in addr:
        packed = socket.inet_pton(socket.AF_INET6, addr)
        hi, lo = struct.unpack("!QQ", packed)
        return int((hi << 64) | lo)
    packed = socket.inet_pton(socket.AF_INET, addr)
    return int(struct.unpack("!I", packed)[0])


def lookup_country(ip_str: str) -> str | None:
    """Look up the ISO 3166-1 alpha-2 country code for an IP.

    Uses binary search for O(log n) performance.

    Args:
        ip_str: An IPv4 or IPv6 address string.

    Returns:
        Two-letter country code (e.g. ``"US"``, ``"DE"``),
        or ``None`` if the database is unavailable or the
        IP is not covered.
    """
    db = _load_database()
    if db is None:
        return None

    starts, ends, countries = db

    try:
        ip_int = _ip_to_int(ip_str)
    except (ValueError, OSError):
        return None

    idx = bisect.bisect_right(starts, ip_int) - 1
    if idx >= 0 and starts[idx] <= ip_int <= ends[idx]:
        return countries[idx]

    return None


def is_available() -> bool:
    """Check whether the geolocation database is loaded."""
    return _load_database() is not None


def lookup_country_for_domain(domain: str) -> str | None:
    """Resolve a domain via DNS and look up its server country.

    Convenience wrapper that does a synchronous DNS lookup
    followed by an IP-to-country lookup.  Returns ``None``
    when the database is unavailable, DNS fails, or the IP
    is not covered.

    Args:
        domain: Hostname to resolve (e.g. ``"cdn.example.com"``).

    Returns:
        Two-letter country code, or ``None``.
    """
    if not is_available():
        return None

    # Cookie domains often have a leading dot (e.g. ".google.com").
    domain = domain.lstrip(".")
    if not domain:
        return None

    try:
        results = socket.getaddrinfo(
            domain,
            None,
            socket.AF_INET,
            socket.SOCK_STREAM,
            0,
            socket.AI_ADDRCONFIG,
        )
        if results:
            ip = str(results[0][4][0])
            country = lookup_country(ip)
            log.debug(
                "Domain geo resolved",
                {"domain": domain, "ip": ip, "country": country},
            )
            return country
    except (socket.gaierror, OSError, IndexError):
        log.debug("Domain geo resolution failed", {"domain": domain})
    return None
