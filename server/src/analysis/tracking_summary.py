"""
Utilities for building tracking data summaries.
Aggregates cookies, scripts, and network requests by domain
and prepares data for LLM analysis.
"""

from __future__ import annotations

import collections

from src.analysis import tracker_patterns
from src.data import loader
from src.models import analysis, tracking_data
from src.utils import logger, url

log = logger.create_logger("TrackingSummary")


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


def _get_third_party_domains(domain_data: dict[str, analysis.DomainData], analyzed_url: str) -> list[str]:
    """Identify third-party domains relative to the analyzed URL."""
    page_base = url.get_base_domain(url.extract_domain(analyzed_url))

    results = []
    for domain in domain_data:
        if url.get_base_domain(domain) != page_base:
            results.append(domain)
    return results


def _build_domain_breakdown(
    domain_data: dict[str, analysis.DomainData],
) -> list[analysis.DomainBreakdown]:
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
    third_party = _get_third_party_domains(domain_data, analyzed_url)

    log.info(
        "Tracking summary built",
        {
            "totalDomains": len(domain_data),
            "thirdPartyDomains": len(third_party),
            "cookies": len(cookies),
            "scripts": len(scripts),
            "requests": len(network_requests),
        },
    )

    return analysis.TrackingSummary(
        analyzed_url=analyzed_url,
        total_cookies=len(cookies),
        total_scripts=len(scripts),
        total_network_requests=len(network_requests),
        local_storage_items=len(local_storage),
        session_storage_items=len(session_storage),
        third_party_domains=third_party,
        domain_breakdown=_build_domain_breakdown(domain_data),
        local_storage=_build_storage_preview(local_storage),
        session_storage=_build_storage_preview(session_storage),
    )


def build_pre_consent_stats(
    cookies: list[tracking_data.TrackedCookie],
    scripts: list[tracking_data.TrackedScript],
    requests: list[tracking_data.NetworkRequest],
    storage: dict[str, list[tracking_data.StorageItem]],
) -> analysis.PreConsentStats:
    """Snapshot tracking data on initial page load.

    Classifies cookies, scripts, and requests as tracking
    vs. legitimate infrastructure using compiled pattern
    databases.  This snapshot is taken before any overlay
    or dialog (including non-consent overlays like sign-in
    prompts) is dismissed.

    We cannot determine from this snapshot alone whether:
    - the observed scripts actually use the cookies present,
    - any dialog is a consent dialog (vs sign-in / paywall),
    - the tracked activity is covered by what the user is
      asked to consent to.

    Args:
        cookies: Currently tracked cookies.
        scripts: Currently tracked scripts.
        requests: Currently tracked network requests.
        storage: Dict with ``local_storage`` and
            ``session_storage`` lists.

    Returns:
        Page-load statistics for scoring calibration.
    """
    tracking_patterns_db = loader.get_tracking_scripts()
    url_combined = tracker_patterns.ALL_URL_TRACKERS_COMBINED
    cookie_combined = tracker_patterns.TRACKING_COOKIE_COMBINED

    tracking_cookies = sum(1 for c in cookies if cookie_combined.search(c.name))
    tracking_scripts = sum(1 for s in scripts if any(t.compiled.search(s.url) for t in tracking_patterns_db) or url_combined.search(s.url))
    tracker_requests = sum(1 for r in requests if r.is_third_party and url_combined.search(r.url))

    return analysis.PreConsentStats(
        total_cookies=len(cookies),
        total_scripts=len(scripts),
        total_requests=len(requests),
        total_local_storage=len(storage["local_storage"]),
        total_session_storage=len(storage["session_storage"]),
        tracking_cookies=tracking_cookies,
        tracking_scripts=tracking_scripts,
        tracker_requests=tracker_requests,
    )
