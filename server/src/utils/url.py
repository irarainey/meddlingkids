"""
URL and domain utility functions for tracking analysis.
"""

from __future__ import annotations

import re
from urllib import parse

_TWO_PART_TLDS = frozenset([
    "co.uk", "com.au", "co.nz", "co.jp", "com.br",
    "co.in", "org.uk", "net.uk", "gov.uk",
])


def extract_domain(url: str) -> str:
    """Extract the hostname from a URL string."""
    try:
        parsed = parse.urlparse(url)
        return parsed.hostname or "unknown"
    except Exception:
        return "unknown"


def get_base_domain(domain: str) -> str:
    """Extract the registrable base domain from a full hostname.

    Handles common multi-part TLDs (e.g. ``co.uk``,
    ``com.au``) and strips a leading ``www.`` prefix.

    Args:
        domain: A hostname like ``"www.example.co.uk"``.

    Returns:
        The base domain, e.g. ``"example.co.uk"``.
    """
    clean = re.sub(r"^www\.", "", domain).lower()
    parts = clean.split(".")
    if len(parts) >= 2:
        last_two = ".".join(parts[-2:])
        if last_two in _TWO_PART_TLDS and len(parts) >= 3:
            return ".".join(parts[-3:])
        return last_two
    return clean


def is_third_party(request_url: str, page_url: str) -> bool:
    """Determine if a request URL is from a third-party domain relative to the page URL."""
    try:
        request_domain = extract_domain(request_url)
        page_domain = extract_domain(page_url)
        return get_base_domain(request_domain) != get_base_domain(page_domain)
    except Exception:
        return True
