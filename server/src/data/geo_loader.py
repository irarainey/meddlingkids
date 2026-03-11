"""IP geolocation database loader.

Loads the DB-IP Lite country database (CC BY 4.0) and
provides O(log n) IP-to-country lookups using binary search
on sorted IPv4/IPv6 integer ranges.

The database file is optional.  When absent, all lookups
return ``None`` and a debug message is logged once.

Attribution: IP Geolocation by DB-IP (https://db-ip.com)
License: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)
"""

from __future__ import annotations

import bisect
import csv
import functools
import gzip
import pathlib
import socket
import struct
import urllib.request
from datetime import UTC, datetime

from src.utils import logger

log = logger.create_logger("GeoLoader")

_GEO_DIR = pathlib.Path(__file__).resolve().parent / "geo"

# Stable symlink name created by scripts/update-geo-db.sh or ensure_database().
_DB_SYMLINK = "dbip-country-lite.csv"

# DB-IP Lite download URL template.  The file is published on
# the 1st of each month and licensed under CC BY 4.0.
_DOWNLOAD_URL = "https://download.db-ip.com/free/dbip-country-lite-{slug}.csv.gz"


def ensure_database() -> bool:
    """Download the DB-IP Lite database if not already present.

    Checks for the symlink/CSV file and, if missing, downloads
    the current month's database from DB-IP.  This is safe to
    call on every startup — it only downloads when needed.

    Returns:
        ``True`` if the database is available after this call.
    """
    csv_path = _GEO_DIR / _DB_SYMLINK
    if csv_path.exists():
        return True

    _GEO_DIR.mkdir(parents=True, exist_ok=True)

    slug = datetime.now(tz=UTC).strftime("%Y-%m")
    filename = f"dbip-country-lite-{slug}.csv"
    csv_file = _GEO_DIR / filename
    gz_file = _GEO_DIR / f"{filename}.gz"

    # If the dated CSV already exists, just create the symlink.
    if csv_file.exists():
        symlink = _GEO_DIR / _DB_SYMLINK
        symlink.symlink_to(filename)
        log.info("IP geolocation database symlink created", {"file": filename})
        return True

    url = _DOWNLOAD_URL.format(slug=slug)
    log.info("Downloading IP geolocation database", {"url": url})

    try:
        urllib.request.urlretrieve(url, gz_file)
    except Exception:
        log.warn(
            "Failed to download IP geolocation database — "
            "country flags will not be shown. "
            "Run scripts/update-geo-db.sh manually if needed.",
        )
        gz_file.unlink(missing_ok=True)
        return False

    try:
        with gzip.open(gz_file, "rb") as f_in, open(csv_file, "wb") as f_out:
            while chunk := f_in.read(65536):
                f_out.write(chunk)
    except Exception:
        log.warn("Failed to decompress IP geolocation database")
        csv_file.unlink(missing_ok=True)
        gz_file.unlink(missing_ok=True)
        return False

    gz_file.unlink(missing_ok=True)

    # Create the stable symlink.
    symlink = _GEO_DIR / _DB_SYMLINK
    symlink.symlink_to(filename)

    log.info("IP geolocation database downloaded", {"file": filename})
    return True


@functools.cache
def _load_database() -> tuple[list[int], list[int], list[str]] | None:
    """Parse the DB-IP Lite CSV into sorted integer ranges.

    Returns a tuple of ``(starts, ends, countries)`` where
    each list is aligned by index.  ``starts`` is sorted in
    ascending order for binary search.

    Uses ``socket.inet_pton`` + ``struct.unpack`` for fast IP
    parsing instead of ``ipaddress.ip_address()`` (~10× faster).

    Returns ``None`` when the database file is not present.
    """
    csv_path = _GEO_DIR / _DB_SYMLINK
    if not csv_path.exists():
        log.debug(
            "IP geolocation database not found — run scripts/update-geo-db.sh to download it",
        )
        return None

    resolved = csv_path.resolve()
    if not resolved.is_relative_to(_GEO_DIR.resolve()):
        log.error(
            "Geo database symlink escapes data directory",
            {"path": str(resolved)},
        )
        return None

    starts: list[int] = []
    ends: list[int] = []
    countries: list[str] = []

    with open(resolved, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
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

    log.info(
        "IP geolocation database loaded",
        {"entries": len(starts)},
    )
    return starts, ends, countries


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
