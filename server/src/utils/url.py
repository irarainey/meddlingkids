"""
URL and domain utility functions for tracking analysis.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import TypedDict
from urllib import parse

import tldextract

from src.data import loader


def extract_domain(url: str) -> str:
    """Extract the hostname from a URL string.

    Returns ``"unknown"`` when the URL cannot be parsed or
    has no hostname.  Callers that use the result as a cache
    key should check for this sentinel first.
    """
    try:
        parsed = parse.urlparse(url)
        return parsed.hostname or "unknown"
    except Exception:
        return "unknown"


def get_base_domain(domain: str) -> str:
    """Extract the registrable base domain from a full hostname.

    Uses the Public Suffix List (via ``tldextract``) to
    correctly handle all TLDs, including multi-part ones
    like ``co.uk``, ``com.au``, ``co.jp``, etc.

    Args:
        domain: A hostname like ``"www.example.co.uk"``.

    Returns:
        The base domain, e.g. ``"example.co.uk"``.
    """
    ext = tldextract.extract(domain)
    registered = ext.top_domain_under_public_suffix
    if registered:
        return registered.lower()
    # Single-label host (e.g. "localhost") or bare suffix.
    return domain.lower()


def is_third_party(request_url: str, page_url: str) -> bool:
    """Determine if a request URL is from a third-party domain.

    Checks the registrable base domain of the request against
    the page.  Also detects CNAME cloaking: if the request
    domain maps to a known tracker via CNAME, it is treated
    as third-party regardless of the apparent domain.

    Args:
        request_url: The URL of the network request.
        page_url: The URL of the page being analysed.

    Returns:
        True if the request is third-party or CNAME-cloaked.
    """
    try:
        request_domain = extract_domain(request_url)
        page_domain = extract_domain(page_url)
        page_base = get_base_domain(page_domain)

        # Standard third-party check
        if get_base_domain(request_domain) != page_base:
            return True

        # CNAME cloaking check: a request that looks
        # first-party may actually resolve to a tracker.

        cname_target = loader.get_cname_target(request_domain)
        if cname_target:
            return get_base_domain(cname_target) != page_base

        return False
    except Exception:
        return True


def get_cname_target(request_url: str) -> str | None:
    """Return the CNAME tracker destination for a request URL.

    Args:
        request_url: The URL to check for CNAME cloaking.

    Returns:
        The real tracker domain, or ``None`` if not cloaked.
    """

    domain = extract_domain(request_url)
    return loader.get_cname_target(domain)


# ============================================================================
# URL safety validation (SSRF prevention)
# ============================================================================

# Hostnames that must never be navigated to.
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata.internal",
    }
)


class UnsafeURLError(ValueError):
    """Raised when a URL fails safety validation."""


async def validate_analysis_url(url: str) -> None:
    """Validate that *url* is safe for server-side navigation.

    Rejects non-HTTP(S) schemes, private/loopback/link-local IPs,
    multicast addresses, and known metadata hostnames to prevent SSRF.

    Uses non-blocking DNS resolution so the event loop is not stalled.

    Args:
        url: The user-supplied URL to validate.

    Raises:
        UnsafeURLError: If the URL is unsafe for analysis.
    """
    parsed = parse.urlparse(url)

    # --- Scheme allowlist ---
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Only http and https URLs are supported (got {parsed.scheme!r})")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeURLError("URL has no hostname")

    # --- Blocked hostnames ---
    hostname_lower = hostname.lower()
    if hostname_lower in _BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"Blocked hostname: {hostname}")

    # --- Resolve and check IP addresses ---
    try:
        # If the hostname is already an IP literal, parse it directly.
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        # It's a DNS name — resolve asynchronously to avoid
        # blocking the event loop.
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(hostname, None)
            addrs = {ipaddress.ip_address(info[4][0]) for info in infos}
        except OSError:
            # DNS resolution failure is fine — the browser will
            # produce its own "name not resolved" error.
            return
        for addr in addrs:
            _check_ip(addr, hostname)
        return

    _check_ip(addr, hostname)


class ResolvedAddress(TypedDict):
    """Pre-resolved address info for pinned DNS connections."""

    hostname: str
    host: str
    port: int
    family: int
    proto: int
    flags: int


async def resolve_and_validate(url: str) -> list[ResolvedAddress]:
    """Resolve DNS for *url*, validate all IPs, and return address info.

    Eliminates DNS rebinding (TOCTOU) by resolving once and returning
    the validated addresses for the caller to pin connections to.

    Args:
        url: The URL to resolve and validate.

    Returns:
        A list of :class:`ResolvedAddress` dicts for use with a
        pinned aiohttp resolver.

    Raises:
        UnsafeURLError: If the URL or any resolved IP is unsafe.
    """
    parsed = parse.urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Only http and https URLs are supported (got {parsed.scheme!r})")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeURLError("URL has no hostname")

    hostname_lower = hostname.lower()
    if hostname_lower in _BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"Blocked hostname: {hostname}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(hostname, port)
    except OSError as exc:
        raise UnsafeURLError(f"DNS resolution failed for {hostname}") from exc

    results: list[ResolvedAddress] = []
    seen: set[str] = set()
    for family, _, _, _, sockaddr in infos:
        ip_str = sockaddr[0]
        if ip_str in seen:
            continue
        seen.add(ip_str)
        addr = ipaddress.ip_address(ip_str)
        _check_ip(addr, hostname)
        results.append(
            ResolvedAddress(
                hostname=hostname,
                host=ip_str,
                port=port,
                family=family,
                proto=0,
                flags=socket.AI_NUMERICHOST,
            )
        )

    if not results:
        raise UnsafeURLError(f"No addresses resolved for {hostname}")

    return results


def _check_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address, hostname: str) -> None:
    """Raise if *addr* is private, loopback, link-local, or multicast."""
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved:
        raise UnsafeURLError(f"URL resolves to a non-public address ({addr}) for host {hostname}")


def validate_url_surface(url: str) -> None:
    """Check scheme and hostname without DNS resolution.

    Use this when the connection is already pinned to validated
    IPs (e.g. after a redirect) so a fresh DNS lookup would
    introduce a TOCTOU window.

    Raises:
        UnsafeURLError: If the scheme is not HTTP(S), the hostname
            is missing, the hostname is blocked, or the hostname
            is an IP literal pointing to a non-public address.
    """
    parsed = parse.urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Only http and https URLs are supported (got {parsed.scheme!r})")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeURLError("URL has no hostname")

    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"Blocked hostname: {hostname}")

    # If the redirect target is an IP literal, validate it directly.
    try:
        addr = ipaddress.ip_address(hostname)
        _check_ip(addr, hostname)
    except ValueError:
        pass
