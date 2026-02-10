"""
URL and domain utility functions for tracking analysis.
"""

from urllib import parse


def extract_domain(url: str) -> str:
    """Extract the hostname from a URL string."""
    try:
        parsed = parse.urlparse(url)
        return parsed.hostname or "unknown"
    except Exception:
        return "unknown"


def _get_base_domain(domain: str) -> str:
    """
    Extract the base domain (last two or three parts) from a full domain.
    Handles common multi-part TLDs like co.uk, com.au, etc.
    """
    parts = domain.split(".")
    if len(parts) > 2 and len(parts[-2]) <= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_third_party(request_url: str, page_url: str) -> bool:
    """Determine if a request URL is from a third-party domain relative to the page URL."""
    try:
        request_domain = extract_domain(request_url)
        page_domain = extract_domain(page_url)
        return _get_base_domain(request_domain) != _get_base_domain(page_domain)
    except Exception:
        return True
