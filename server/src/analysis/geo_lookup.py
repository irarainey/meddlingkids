"""DNS-based geolocation for third-party domains.

Resolves domain names to IP addresses and looks up their
geographic location using the DB-IP Lite database.  Results
are cached per domain to avoid redundant DNS queries during
a single analysis run.

This module is designed for privacy analysis — it identifies
which countries host the servers that tracking scripts and
network requests communicate with, which is relevant for
GDPR jurisdictional assessments.
"""

from __future__ import annotations

import asyncio
import functools
import socket

from src.data import geo_loader
from src.utils import logger

log = logger.create_logger("GeoLookup")

# Maximum concurrent DNS lookups to prevent flooding.
_MAX_CONCURRENT = 20


@functools.lru_cache(maxsize=4096)
def _resolve_domain(domain: str) -> str | None:
    """Resolve a domain to its first IPv4 address.

    Uses the system resolver via ``socket.getaddrinfo``.
    Returns ``None`` on resolution failure.

    Args:
        domain: Hostname to resolve.

    Returns:
        An IPv4 address string, or ``None``.
    """
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
            addr = str(results[0][4][0])
            return addr
    except (socket.gaierror, OSError, IndexError):
        pass
    return None


def resolve_domain_country(domain: str) -> str | None:
    """Resolve a domain and look up its server country.

    Combines DNS resolution with IP geolocation lookup.
    Results are cached via the underlying ``_resolve_domain``
    LRU cache.

    Args:
        domain: Hostname to resolve and geo-locate.

    Returns:
        ISO 3166-1 alpha-2 country code, or ``None`` if
        resolution fails or the database is unavailable.
    """
    # Cookie domains often have a leading dot (e.g. ".google.com").
    domain = domain.lstrip(".")
    if not domain:
        return None
    ip = _resolve_domain(domain)
    if ip is None:
        log.debug("Domain geo resolution failed", {"domain": domain})
        return None
    country = geo_loader.lookup_country(ip)
    log.debug(
        "Domain geo resolved",
        {"domain": domain, "ip": ip, "country": country},
    )
    return country


async def resolve_domains_countries(
    domains: list[str],
) -> dict[str, str | None]:
    """Resolve multiple domains to country codes concurrently.

    Uses a semaphore to limit concurrent DNS lookups.
    Failures are silently mapped to ``None``.

    Args:
        domains: List of hostnames to resolve.

    Returns:
        A ``{domain: country_code}`` mapping.  Country code
        is ``None`` for domains that could not be resolved
        or looked up.
    """
    if not geo_loader.is_available():
        return {}

    sem = asyncio.Semaphore(_MAX_CONCURRENT)
    loop = asyncio.get_running_loop()

    async def _lookup(domain: str) -> tuple[str, str | None]:
        async with sem:
            try:
                country = await loop.run_in_executor(
                    None,
                    resolve_domain_country,
                    domain,
                )
            except Exception:
                country = None
            return domain, country

    tasks = [_lookup(d) for d in domains]
    results = await asyncio.gather(*tasks)

    resolved = {d: c for d, c in results if c is not None}
    log.info(
        "Domain geolocation complete",
        {"total": len(domains), "resolved": len(resolved)},
    )
    return dict(results)
