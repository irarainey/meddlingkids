"""
Utilities for building tracking data summaries.
Aggregates cookies, scripts, and network requests by domain
and prepares data for LLM analysis.
"""

from __future__ import annotations

from src.types.tracking import (
    DomainBreakdown,
    DomainData,
    NetworkRequest,
    StorageItem,
    TrackedCookie,
    TrackedScript,
    TrackingSummary,
)


def _group_by_domain(
    cookies: list[TrackedCookie],
    scripts: list[TrackedScript],
    network_requests: list[NetworkRequest],
) -> dict[str, DomainData]:
    """Group tracking data (cookies, scripts, network requests) by domain."""
    domain_data: dict[str, DomainData] = {}

    for cookie in cookies or []:
        if cookie.domain not in domain_data:
            domain_data[cookie.domain] = DomainData()
        domain_data[cookie.domain].cookies.append(cookie)

    for script in scripts or []:
        if script.domain not in domain_data:
            domain_data[script.domain] = DomainData()
        domain_data[script.domain].scripts.append(script)

    for request in network_requests or []:
        if request.domain not in domain_data:
            domain_data[request.domain] = DomainData()
        domain_data[request.domain].network_requests.append(request)

    return domain_data


def _get_third_party_domains(
    domain_data: dict[str, DomainData], analyzed_url: str
) -> list[str]:
    """Identify third-party domains relative to the analyzed URL."""
    from urllib.parse import urlparse

    results = []
    for domain in domain_data:
        try:
            page_hostname = urlparse(analyzed_url).hostname or ""
            page_base = ".".join(page_hostname.split(".")[-2:])
            domain_base = ".".join(domain.split(".")[-2:])
            if page_base != domain_base:
                results.append(domain)
        except Exception:
            results.append(domain)
    return results


def _build_domain_breakdown(domain_data: dict[str, DomainData]) -> list[DomainBreakdown]:
    """Build a summary breakdown for each domain's tracking activity."""
    return [
        DomainBreakdown(
            domain=domain,
            cookie_count=len(data.cookies),
            cookie_names=[c.name for c in data.cookies],
            script_count=len(data.scripts),
            request_count=len(data.network_requests),
            request_types=list({r.resource_type for r in data.network_requests}),
        )
        for domain, data in domain_data.items()
    ]


def _build_storage_preview(items: list[StorageItem]) -> list[dict[str, str]]:
    """Build preview of storage items for analysis."""
    return [{"key": item.key, "valuePreview": item.value[:100]} for item in (items or [])]


def build_tracking_summary(
    cookies: list[TrackedCookie],
    scripts: list[TrackedScript],
    network_requests: list[NetworkRequest],
    local_storage: list[StorageItem],
    session_storage: list[StorageItem],
    analyzed_url: str,
) -> TrackingSummary:
    """Build a complete tracking summary for LLM privacy analysis."""
    domain_data = _group_by_domain(cookies, scripts, network_requests)

    return TrackingSummary(
        analyzed_url=analyzed_url,
        total_cookies=len(cookies) if cookies else 0,
        total_scripts=len(scripts) if scripts else 0,
        total_network_requests=len(network_requests) if network_requests else 0,
        local_storage_items=len(local_storage) if local_storage else 0,
        session_storage_items=len(session_storage) if session_storage else 0,
        third_party_domains=_get_third_party_domains(domain_data, analyzed_url),
        domain_breakdown=_build_domain_breakdown(domain_data),
        local_storage=_build_storage_preview(local_storage),
        session_storage=_build_storage_preview(session_storage),
    )
