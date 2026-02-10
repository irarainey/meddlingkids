"""
Utilities for building tracking data summaries.
Aggregates cookies, scripts, and network requests by domain
and prepares data for LLM analysis.
"""

from __future__ import annotations

import collections
from urllib import parse

from src.types import analysis, tracking_data


def _group_by_domain(
    cookies: list[tracking_data.TrackedCookie],
    scripts: list[tracking_data.TrackedScript],
    network_requests: list[tracking_data.NetworkRequest],
) -> dict[str, analysis.DomainData]:
    """Group tracking data (cookies, scripts, network requests) by domain."""
    domain_data: dict[str, analysis.DomainData] = collections.defaultdict(analysis.DomainData)

    for cookie in cookies:
        domain_data[cookie.domain].cookies.append(cookie)

    for script in scripts:
        domain_data[script.domain].scripts.append(script)

    for request in network_requests:
        domain_data[request.domain].network_requests.append(request)

    return domain_data


def _get_third_party_domains(
    domain_data: dict[str, analysis.DomainData], analyzed_url: str
) -> list[str]:
    """Identify third-party domains relative to the analyzed URL."""
    page_hostname = parse.urlparse(analyzed_url).hostname or ""
    page_base = ".".join(page_hostname.split(".")[-2:])

    results = []
    for domain in domain_data:
        domain_base = ".".join(domain.split(".")[-2:])
        if page_base != domain_base:
            results.append(domain)
    return results


def _build_domain_breakdown(domain_data: dict[str, analysis.DomainData]) -> list[analysis.DomainBreakdown]:
    """Build a summary breakdown for each domain's tracking activity."""
    return [
        analysis.DomainBreakdown(
            domain=domain,
            cookie_count=len(data.cookies),
            cookie_names=[c.name for c in data.cookies],
            script_count=len(data.scripts),
            request_count=len(data.network_requests),
            request_types=list({r.resource_type for r in data.network_requests}),
        )
        for domain, data in domain_data.items()
    ]


def _build_storage_preview(items: list[tracking_data.StorageItem]) -> list[dict[str, str]]:
    """Build preview of storage items for analysis."""
    return [{"key": item.key, "valuePreview": item.value[:100]} for item in items]


def build_tracking_summary(
    cookies: list[tracking_data.TrackedCookie],
    scripts: list[tracking_data.TrackedScript],
    network_requests: list[tracking_data.NetworkRequest],
    local_storage: list[tracking_data.StorageItem],
    session_storage: list[tracking_data.StorageItem],
    analyzed_url: str,
) -> analysis.TrackingSummary:
    """Build a complete tracking summary for LLM privacy analysis."""
    domain_data = _group_by_domain(cookies, scripts, network_requests)

    return analysis.TrackingSummary(
        analyzed_url=analyzed_url,
        total_cookies=len(cookies),
        total_scripts=len(scripts),
        total_network_requests=len(network_requests),
        local_storage_items=len(local_storage),
        session_storage_items=len(session_storage),
        third_party_domains=_get_third_party_domains(domain_data, analyzed_url),
        domain_breakdown=_build_domain_breakdown(domain_data),
        local_storage=_build_storage_preview(local_storage),
        session_storage=_build_storage_preview(session_storage),
    )
