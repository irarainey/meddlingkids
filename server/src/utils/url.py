"""
URL and domain utility functions for tracking analysis.
"""

from __future__ import annotations

import asyncio
import ipaddress
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


def _check_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address, hostname: str) -> None:
    """Raise if *addr* is private, loopback, link-local, or multicast."""
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved:
        raise UnsafeURLError(f"URL resolves to a non-public address ({addr}) for host {hostname}")
