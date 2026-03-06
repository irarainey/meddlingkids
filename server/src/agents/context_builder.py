"""Shared context builder for LLM analysis prompts.

Both the tracking-analysis agent and the structured-report agent
require data context for their LLM calls.  The tracking-analysis
agent gets the *full* context (it covers all topics in one call).
The structured-report agent calls the LLM once per section and
each section receives only the context it actually needs, via
:func:`build_section_context` and the per-section configs in
:data:`SECTION_CONFIGS`.
"""

from __future__ import annotations

import collections
import dataclasses
import json
from typing import TYPE_CHECKING

from src.agents import gdpr_context
from src.analysis import domain_cache, domain_classifier
from src.data import loader
from src.models import analysis, consent, report
from src.utils import risk

if TYPE_CHECKING:
    pass


# ====================================================================
# Section content flags
# ====================================================================


@dataclasses.dataclass(frozen=True, slots=True)
class SectionNeeds:
    """Declares which context blocks a report section requires.

    Each flag corresponds to a data block in
    :func:`build_analysis_context`.  Blocks marked ``False``
    are omitted from the context string for that section,
    saving tokens.
    """

    url: bool = True
    data_summary: bool = True
    pre_consent_stats: bool = False
    third_party_domains: bool = False
    domain_breakdown: bool = False
    local_storage: bool = False
    session_storage: bool = False
    consent_info: bool = False
    privacy_score: bool = False
    domain_knowledge: bool = False
    gdpr_reference: bool = False
    tracking_cookie_db: bool = False
    disconnect_db: bool = False
    media_group: bool = False
    include_partner_urls: bool = False
    storage_summary_only: bool = False
    consent_delta: bool = False
    tc_string_data: bool = False
    social_platforms: bool = False


# Per-section configs derived from the needs-matrix audit.
# Each entry maps a report section name to the minimal set
# of context blocks it requires.

SECTION_CONFIGS: dict[str, SectionNeeds] = {
    "tracking-technologies": SectionNeeds(
        third_party_domains=True,
        domain_breakdown=True,
        local_storage=True,
        session_storage=True,
        storage_summary_only=True,
        domain_knowledge=True,
        tracking_cookie_db=True,
        disconnect_db=True,
        media_group=True,
    ),
    "data-collection": SectionNeeds(
        third_party_domains=True,
        domain_breakdown=True,
        local_storage=True,
        session_storage=True,
        storage_summary_only=True,
        domain_knowledge=True,
        tracking_cookie_db=True,
        disconnect_db=True,
    ),
    "third-party-services": SectionNeeds(
        third_party_domains=True,
        domain_knowledge=True,
        disconnect_db=True,
        media_group=True,
    ),
    "privacy-risk": SectionNeeds(
        pre_consent_stats=True,
        consent_delta=True,
        third_party_domains=True,
        domain_breakdown=True,
        privacy_score=True,
        domain_knowledge=True,
        tracking_cookie_db=True,
        disconnect_db=True,
    ),
    "cookie-analysis": SectionNeeds(
        domain_breakdown=True,
        domain_knowledge=True,
        gdpr_reference=True,
        tracking_cookie_db=True,
        disconnect_db=True,
    ),
    "storage-analysis": SectionNeeds(
        local_storage=True,
        session_storage=True,
    ),
    "consent-analysis": SectionNeeds(
        third_party_domains=True,
        consent_info=True,
        consent_delta=True,
        tc_string_data=True,
        domain_knowledge=True,
        gdpr_reference=True,
        tracking_cookie_db=True,
        disconnect_db=True,
        include_partner_urls=True,
    ),
    "consent-digest": SectionNeeds(
        third_party_domains=True,
        consent_info=True,
        pre_consent_stats=True,
    ),
    "social-media-implications": SectionNeeds(
        third_party_domains=True,
        domain_breakdown=True,
        domain_knowledge=True,
        tracking_cookie_db=True,
        disconnect_db=True,
        social_platforms=True,
    ),
    "recommendations": SectionNeeds(
        pre_consent_stats=True,
        privacy_score=True,
    ),
}

# ── Public API ──────────────────────────────────────────────────


def build_analysis_context(
    tracking_summary: analysis.TrackingSummary,
    *,
    consent_details: consent.ConsentDetails | None = None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
    score_breakdown: analysis.ScoreBreakdown | None = None,
    domain_knowledge: domain_cache.DomainKnowledge | None = None,
    include_raw_consent_text: bool = False,
    include_partner_urls: bool = False,
    decoded_cookies: dict[str, object] | None = None,
) -> str:
    """Build a comprehensive analysis-context string.

    The returned string contains every data section needed by
    the LLM — summary statistics, pre-consent activity,
    third-party domains, domain breakdown, storage data,
    consent-dialog information, deterministic score, domain
    knowledge, GDPR/TCF reference, and tracking-database
    context.

    Args:
        tracking_summary: Collected tracking data summary.
        consent_details: Optional consent dialog info.
        pre_consent_stats: Optional pre-consent page-load
            statistics.
        score_breakdown: Deterministic privacy score, if
            available.
        domain_knowledge: Optional prior-run domain
            classifications for consistency anchoring.
        include_raw_consent_text: When ``True``, append up
            to 3 000 characters of raw consent text.
        include_partner_urls: When ``True``, include each
            partner's URL in the consent section.

    Returns:
        Multi-section markdown context string.
    """
    local_json = json.dumps(tracking_summary.local_storage)
    session_json = json.dumps(tracking_summary.session_storage)

    sections: list[str] = [
        f"URL analysed: {tracking_summary.analyzed_url}",
        "",
        "## Data Summary",
        f"- Total Cookies: {tracking_summary.total_cookies}",
        f"- Total Scripts: {tracking_summary.total_scripts}",
        f"- Total Network Requests: {tracking_summary.total_network_requests}",
        f"- LocalStorage Items: {tracking_summary.local_storage_items}",
        f"- SessionStorage Items: {tracking_summary.session_storage_items}",
        f"- Third-Party Domains: {len(tracking_summary.third_party_domains)}",
    ]

    if pre_consent_stats:
        sections.extend(_build_pre_consent_lines(pre_consent_stats))

    sections.extend(
        [
            "",
            "## Domain Breakdown (grouped by organization)",
            _group_domain_breakdown_by_org(tracking_summary.domain_breakdown),
            "",
            f"## LocalStorage Data\n{local_json}",
            "",
            f"## SessionStorage Data\n{session_json}",
        ]
    )

    if consent_details and (consent_details.categories or consent_details.partners or consent_details.claimed_partner_count):
        sections.extend(
            _build_consent_lines(
                consent_details,
                include_raw_text=include_raw_consent_text,
                include_partner_urls=include_partner_urls,
            )
        )

    if score_breakdown:
        sections.extend(_build_score_lines(score_breakdown))

    if domain_knowledge:
        sections.append(domain_cache.build_context_hint(domain_knowledge))

    # Note: GDPR/TCF reference (~4.5K), tracking cookie DB (~13K),
    # and Disconnect DB (~11K) are omitted from the full context
    # to keep the TrackingAnalysisAgent prompt under LLM timeout
    # thresholds.  These static reference databases are included
    # in section-specific contexts via build_section_context()
    # where they're actually needed (cookie-analysis, consent-
    # analysis).  The TrackingAnalysisAgent's model already has
    # strong knowledge of common tracking cookies and TCF purposes.

    disconnect_ctx = loader.build_disconnect_context(
        tracking_summary.third_party_domains,
    )
    if disconnect_ctx:
        sections.append(disconnect_ctx)

    media_ctx = loader.build_media_group_context(
        tracking_summary.analyzed_url,
    )
    if media_ctx:
        sections.append(media_ctx)

    # ── Data available but historically not included ─────────
    if pre_consent_stats:
        sections.extend(_build_consent_delta_lines(pre_consent_stats, tracking_summary))

    if consent_details:
        tc_lines = _build_tc_string_lines(consent_details)
        if tc_lines:
            sections.extend(tc_lines)

    if decoded_cookies:
        sections.extend(_build_decoded_cookies_lines(decoded_cookies))

    return "\n".join(sections)


def build_section_context(
    section_name: str,
    tracking_summary: analysis.TrackingSummary,
    *,
    consent_details: consent.ConsentDetails | None = None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
    score_breakdown: analysis.ScoreBreakdown | None = None,
    domain_knowledge: domain_cache.DomainKnowledge | None = None,
    social_media_trackers: list[report.TrackerEntry] | None = None,
) -> str:
    """Build a tailored context string for a single report section.

    Uses the :data:`SECTION_CONFIGS` needs-matrix to include
    only the data blocks relevant to *section_name*, reducing
    token usage by 30–90 % compared to the full context.

    Falls back to the full context if *section_name* is not
    found in :data:`SECTION_CONFIGS`.

    Args:
        section_name: Report section identifier (e.g.
            ``"cookie-analysis"``).
        tracking_summary: Collected tracking data summary.
        consent_details: Optional consent dialog info.
        pre_consent_stats: Optional pre-consent statistics.
        score_breakdown: Deterministic privacy score.
        domain_knowledge: Optional cached domain classifications.
        social_media_trackers: Pre-classified social media
            tracker entries from deterministic classification.

    Returns:
        Multi-section markdown context string.
    """
    needs = SECTION_CONFIGS.get(section_name)
    if needs is None:
        # Unknown section — send everything to be safe.
        return build_analysis_context(
            tracking_summary,
            consent_details=consent_details,
            pre_consent_stats=pre_consent_stats,
            score_breakdown=score_breakdown,
            domain_knowledge=domain_knowledge,
            include_partner_urls=True,
        )

    sections: list[str] = []

    # ── Always-included header ──────────────────────────────
    if needs.url:
        sections.append(f"URL analysed: {tracking_summary.analyzed_url}")

    if needs.data_summary:
        sections.extend(
            [
                "",
                "## Data Summary",
                f"- Total Cookies: {tracking_summary.total_cookies}",
                f"- Total Scripts: {tracking_summary.total_scripts}",
                f"- Total Network Requests: {tracking_summary.total_network_requests}",
                f"- LocalStorage Items: {tracking_summary.local_storage_items}",
                f"- SessionStorage Items: {tracking_summary.session_storage_items}",
                f"- Third-Party Domains: {len(tracking_summary.third_party_domains)}",
            ]
        )

    # ── Optional blocks ─────────────────────────────────────
    if needs.pre_consent_stats and pre_consent_stats:
        sections.extend(_build_pre_consent_lines(pre_consent_stats))

    if needs.third_party_domains:
        sections.extend(
            [
                "",
                "## Third-Party Domains (grouped by organization)",
                _group_domains_by_org(tracking_summary.third_party_domains),
            ]
        )

    if needs.domain_breakdown:
        sections.extend(
            [
                "",
                "## Domain Breakdown (grouped by organization)",
                _group_domain_breakdown_by_org(tracking_summary.domain_breakdown),
            ]
        )

    if needs.local_storage:
        if needs.storage_summary_only:
            summary = _build_storage_summary(
                tracking_summary.local_storage,
                "localStorage",
            )
            sections.extend(["", summary])
        else:
            local_json = json.dumps(tracking_summary.local_storage)
            sections.extend(["", f"## LocalStorage Data\n{local_json}"])

    if needs.session_storage:
        if needs.storage_summary_only:
            summary = _build_storage_summary(
                tracking_summary.session_storage,
                "sessionStorage",
            )
            sections.extend(["", summary])
        else:
            session_json = json.dumps(tracking_summary.session_storage)
            sections.extend(["", f"## SessionStorage Data\n{session_json}"])

    if (
        needs.consent_info
        and consent_details
        and (consent_details.categories or consent_details.partners or consent_details.claimed_partner_count)
    ):
        sections.extend(
            _build_consent_lines(
                consent_details,
                include_raw_text=False,
                include_partner_urls=needs.include_partner_urls,
            )
        )

    if needs.privacy_score and score_breakdown:
        sections.extend(_build_score_lines(score_breakdown))

    if needs.domain_knowledge and domain_knowledge:
        sections.append(domain_cache.build_context_hint(domain_knowledge))

    if needs.gdpr_reference:
        sections.append(
            "\n"
            + gdpr_context.build_gdpr_reference(
                heading="## GDPR / TCF Reference Data",
            ),
        )

    if needs.tracking_cookie_db:
        cookie_ctx = loader.build_tracking_cookie_context()
        if cookie_ctx:
            sections.append(cookie_ctx)

    if needs.disconnect_db:
        disconnect_ctx = loader.build_disconnect_context(
            tracking_summary.third_party_domains,
        )
        if disconnect_ctx:
            sections.append(disconnect_ctx)

    if needs.media_group:
        media_ctx = loader.build_media_group_context(
            tracking_summary.analyzed_url,
        )
        if media_ctx:
            sections.append(media_ctx)

    # ── Gap fills ───────────────────────────────────────────

    if needs.consent_delta and pre_consent_stats:
        sections.extend(
            _build_consent_delta_lines(
                pre_consent_stats,
                tracking_summary,
            )
        )

    if needs.tc_string_data and consent_details:
        tc_lines = _build_tc_string_lines(consent_details)
        if tc_lines:
            sections.extend(tc_lines)

    if needs.social_platforms and social_media_trackers:
        sections.extend(_build_social_platforms_lines(social_media_trackers))

    return "\n".join(sections)


# ── Domain compression helpers ──────────────────────────────────
#
# Group raw per-domain data by parent organization using the
# Disconnect + partner DBs.  This compresses Bristol Post's
# 353 domains → ~144 groups, saving ~40% of context chars.


def _group_domains_by_org(
    domains: list[str],
) -> str:
    """Group third-party domains by parent organization.

    Uses :func:`domain_classifier.classify_domain` (Disconnect
    + partner DBs + heuristics) to resolve each domain to its
    parent company.  Unknown domains are listed individually
    under an ``Unclassified`` heading.

    Returns:
        Multi-line markdown text with org-grouped domains.
    """
    orgs: dict[str, list[str]] = collections.defaultdict(list)
    unclassified: list[str] = []

    for domain in domains:
        _category, company = domain_classifier.classify_domain(domain)
        if company:
            orgs[company].append(domain)
        else:
            unclassified.append(domain)

    lines: list[str] = []
    for company in sorted(orgs):
        dom_list = sorted(orgs[company])
        if len(dom_list) <= 3:
            lines.append(f"- **{company}**: {', '.join(dom_list)}")
        else:
            lines.append(f"- **{company}** ({len(dom_list)} domains): {', '.join(dom_list[:3])}, ...")

    if unclassified:
        lines.append(f"- _Unclassified_ ({len(unclassified)}): {', '.join(sorted(unclassified)[:10])}")
        if len(unclassified) > 10:
            lines.append(f"  ... and {len(unclassified) - 10} more")

    return "\n".join(lines)


def _group_domain_breakdown_by_org(
    breakdown: list[analysis.DomainBreakdown],
) -> str:
    """Collapse per-domain breakdown entries by parent organization.

    Sums cookie, script, and request counts across sibling
    domains belonging to the same company.  Merges cookie
    names and request types into union sets.

    Returns:
        JSON string of organization-level breakdown objects.
    """

    @dataclasses.dataclass
    class _OrgBucket:
        organization: str
        domains: list[str] = dataclasses.field(default_factory=list)
        cookie_count: int = 0
        cookie_names: set[str] = dataclasses.field(default_factory=set)
        script_count: int = 0
        request_count: int = 0
        request_types: set[str] = dataclasses.field(default_factory=set)

    org_data: dict[str, _OrgBucket] = {}
    unclassified: list[dict[str, object]] = []

    for entry in breakdown:
        _category, company = domain_classifier.classify_domain(entry.domain)
        if company:
            key = company.lower()
            if key not in org_data:
                org_data[key] = _OrgBucket(organization=company)
            bucket = org_data[key]
            bucket.domains.append(entry.domain)
            bucket.cookie_count += entry.cookie_count
            bucket.cookie_names |= set(entry.cookie_names)
            bucket.script_count += entry.script_count
            bucket.request_count += entry.request_count
            bucket.request_types |= set(entry.request_types)
        else:
            unclassified.append(entry.model_dump(exclude_defaults=True))

    # Serialize to JSON-friendly dicts.
    result: list[dict[str, object]] = []
    for bucket in sorted(org_data.values(), key=lambda b: b.organization):
        result.append(
            {
                "organization": bucket.organization,
                "domain_count": len(bucket.domains),
                "cookie_count": bucket.cookie_count,
                "cookie_names": sorted(bucket.cookie_names),
                "script_count": bucket.script_count,
                "request_count": bucket.request_count,
                "request_types": sorted(bucket.request_types),
            }
        )

    result.extend(unclassified)
    return json.dumps(result)


def _build_storage_summary(
    items: list[dict[str, str]],
    storage_type: str,
) -> str:
    """Build a compact statistical summary of browser storage items.

    Classifies each key against the tracking-storage pattern
    database and groups by purpose (analytics, advertising,
    identity, functional, etc.).  Sections that need the full
    key-value list (Storage Analysis) bypass this and get the
    raw JSON instead.

    Args:
        items: Storage items as ``{"key": ..., "valuePreview": ...}``.
        storage_type: Display label (``"localStorage"`` or
            ``"sessionStorage"``).

    Returns:
        Compact markdown summary string.
    """
    if not items:
        return f"## {storage_type} Summary\nNo items."

    patterns = loader.get_tracking_storage_patterns()

    tracking: dict[str, list[str]] = collections.defaultdict(list)
    functional: list[str] = []

    for item in items:
        key = item.get("key", "")
        matched = False
        for pattern, _desc, set_by, purpose in patterns:
            if pattern.search(key):
                label = f"{set_by} ({purpose})" if set_by else purpose
                tracking[label].append(key)
                matched = True
                break
        if not matched:
            functional.append(key)

    lines = [
        f"## {storage_type} Summary ({len(items)} items)",
    ]

    if tracking:
        lines.append(f"- **Tracking-related** ({sum(len(v) for v in tracking.values())} items):")
        for label in sorted(tracking):
            keys = tracking[label]
            if len(keys) <= 3:
                lines.append(f"  - {label}: {', '.join(keys)}")
            else:
                lines.append(f"  - {label} ({len(keys)} keys): {', '.join(keys[:3])}, ...")

    if functional:
        lines.append(f"- **Other/functional** ({len(functional)} items): {', '.join(functional[:8])}")
        if len(functional) > 8:
            lines[-1] += f", ... (+{len(functional) - 8} more)"

    return "\n".join(lines)


# ── Gap-fill context helpers ────────────────────────────────────


def _build_consent_delta_lines(
    pre: analysis.PreConsentStats,
    tracking_summary: analysis.TrackingSummary,
) -> list[str]:
    """Build a consent-delta section showing what changed after consent.

    Computes the difference between pre-consent counts and
    final totals to show how many cookies, scripts, and
    requests appeared after the consent dialog was dismissed.
    """
    new_cookies = tracking_summary.total_cookies - pre.total_cookies
    new_scripts = tracking_summary.total_scripts - pre.total_scripts
    new_requests = tracking_summary.total_network_requests - pre.total_requests

    if new_cookies <= 0 and new_scripts <= 0 and new_requests <= 0:
        return []

    return [
        "",
        "## Post-Consent Changes (what appeared after dialog dismissal)",
        f"- New cookies after consent: {new_cookies} (was {pre.total_cookies}, now {tracking_summary.total_cookies})",
        f"- New scripts after consent: {new_scripts} (was {pre.total_scripts}, now {tracking_summary.total_scripts})",
        f"- New requests after consent: {new_requests} (was {pre.total_requests}, now {tracking_summary.total_network_requests})",
    ]


def _build_tc_string_lines(
    cd: consent.ConsentDetails,
) -> list[str]:
    """Build a compact TC/AC string summary for the consent section.

    Extracts purpose consents, vendor counts, LI signals,
    CMP identity, and validation findings from the decoded
    TC string data stored on ``ConsentDetails``.
    """
    lines: list[str] = []

    tc = cd.tc_string_data
    if tc:
        lines.extend(
            [
                "",
                "## Decoded TC String (IAB TCF v2.2)",
                f"- CMP ID: {tc.get('cmpId', 'unknown')} v{tc.get('cmpVersion', '?')}",
                f"- Policy version: {tc.get('tcfPolicyVersion', '?')}",
                f"- Purposes consented: {tc.get('purposeConsents', [])}",
                f"- Purposes with legitimate interest: {tc.get('purposeLegitimateInterests', [])}",
                f"- Special features opted in: {tc.get('specialFeatureOptIns', [])}",
                f"- Vendors consented: {tc.get('vendorConsentCount', 0)}",
                f"- Vendors with legitimate interest: {tc.get('vendorLiCount', 0)}",
            ]
        )
        # Resolved vendor names (if available).
        resolved = tc.get("resolvedVendorConsents")
        if resolved and isinstance(resolved, list):
            names = [v.get("name", "") for v in resolved[:20] if isinstance(v, dict)]
            if names:
                lines.append(f"- Top consented vendors: {', '.join(names)}")
            unresolved = tc.get("unresolvedVendorConsentCount", 0)
            if unresolved:
                lines.append(f"- Unresolved vendor IDs: {unresolved}")

    ac = cd.ac_string_data
    if ac:
        lines.extend(
            [
                "",
                "## Decoded AC String (Google Additional Consent)",
                f"- Provider count: {ac.get('vendorCount', 0)}",
            ]
        )
        resolved_ac = ac.get("resolvedProviders")
        if resolved_ac and isinstance(resolved_ac, list):
            names = [p.get("name", "") for p in resolved_ac[:15] if isinstance(p, dict)]
            if names:
                lines.append(f"- Top providers: {', '.join(names)}")

    tc_val = cd.tc_validation
    if tc_val:
        findings = tc_val.get("findings", [])
        if findings and isinstance(findings, list):
            lines.extend(
                [
                    "",
                    "## TC String Validation Findings",
                ]
            )
            for f in findings[:5]:
                if isinstance(f, dict):
                    lines.append(f"- [{f.get('severity', 'info')}] {f.get('message', '')}")

    return lines


def _build_social_platforms_lines(
    trackers: list[report.TrackerEntry],
) -> list[str]:
    """Build a pre-classified social media platforms section.

    Passes deterministic social-media tracker classifications
    to the LLM so it doesn't have to re-derive platform
    identities from raw domain lists.
    """
    if not trackers:
        return []

    lines = [
        "",
        "## Detected Social Media Platforms (deterministic classification)",
    ]
    for t in trackers:
        domains = ", ".join(t.domains[:5])
        cookies = ", ".join(t.cookies[:5]) if t.cookies else "none"
        lines.append(f"- **{t.name}**: domains=[{domains}], cookies=[{cookies}], purpose={t.purpose}")
    return lines


def _build_decoded_cookies_lines(
    decoded: dict[str, object],
) -> list[str]:
    """Build a compact summary of decoded privacy cookie signals.

    Includes USP/GPP strings, Google Analytics client IDs,
    Facebook pixel data, OneTrust/Cookiebot consent categories,
    Google Ads click IDs, and Google SOCS consent mode.

    Args:
        decoded: Dict of decoded cookie signal groups from
            ``cookie_decoders.decode_all_privacy_cookies()``.

    Returns:
        List of markdown lines.
    """
    if not decoded:
        return []

    lines = [
        "",
        "## Decoded Privacy Cookie Signals",
    ]
    for signal_name, data in decoded.items():
        if isinstance(data, dict):
            # Compact single-line summary for each signal.
            summary_parts = [f"{k}={v}" for k, v in list(data.items())[:6]]
            lines.append(f"- **{signal_name}**: {', '.join(summary_parts)}")
        elif isinstance(data, list):
            lines.append(f"- **{signal_name}**: {len(data)} items")
        else:
            lines.append(f"- **{signal_name}**: {data}")
    return lines


# ── Private section helpers ─────────────────────────────────────


def _build_pre_consent_lines(
    stats: analysis.PreConsentStats,
) -> list[str]:
    """Build pre-consent page-load activity lines.

    Args:
        stats: Pre-consent statistics snapshot.

    Returns:
        List of lines (newline-joined by the caller).
    """
    return [
        "",
        "## Activity on Initial Page Load (before any dialogs were dismissed)",
        "NOTE: This is what was present when the page first"
        " loaded. We cannot confirm whether these scripts use"
        " the cookies listed, whether any dialog is a consent"
        " dialog, or whether this activity falls within the"
        " scope of what the user is asked to consent to.",
        f"- Cookies on load: {stats.total_cookies} ({stats.tracking_cookies} matched tracking patterns)",
        f"- Scripts on load: {stats.total_scripts} ({stats.tracking_scripts} matched tracking patterns)",
        f"- Requests on load: {stats.total_requests} ({stats.tracker_requests} matched tracking patterns)",
    ]


def _build_consent_lines(
    cd: consent.ConsentDetails,
    *,
    include_raw_text: bool = False,
    include_partner_urls: bool = False,
) -> list[str]:
    """Build consent-dialog information lines.

    Args:
        cd: Consent details from the dialog.
        include_raw_text: Append raw text excerpts.
        include_partner_urls: Show partner URLs.

    Returns:
        List of lines.
    """
    cats = (
        "\n".join(f"- **{c.name}** ({'Required' if c.required else 'Optional'}): {c.description}" for c in cd.categories)
        or "None disclosed"
    )

    partners = "\n".join(_format_partner(p, include_url=include_partner_urls) for p in cd.partners[:50]) or "None listed"

    claimed_line = ""
    if cd.claimed_partner_count:
        claimed_line = f"\n### Claimed Partner Count: {cd.claimed_partner_count}"

    purposes = "\n".join(f"- {p}" for p in cd.purposes) or "None"

    lines: list[str] = [
        "",
        "## Consent Dialog Information",
        f"### Categories Disclosed ({len(cd.categories)})",
        cats,
        f"### Partners Listed ({len(cd.partners)})",
        partners,
        claimed_line,
        "### Stated Purposes",
        purposes,
    ]

    if include_raw_text and cd.raw_text:
        lines.extend(
            [
                "",
                "### Raw Consent Text Excerpts",
                cd.raw_text[:3000],
            ]
        )

    return lines


def _format_partner(
    p: consent.ConsentPartner,
    *,
    include_url: bool = False,
) -> str:
    """Format a single consent partner for LLM context.

    Args:
        p: Consent partner with classification metadata.
        include_url: Append the partner URL when available.

    Returns:
        Formatted markdown line.
    """
    risk_tag = f" [{p.risk_level.upper()} RISK]" if p.risk_level else ""
    category = f" ({p.risk_category})" if p.risk_category else ""
    data = f" | Data: {', '.join(p.data_collected)}" if p.data_collected else ""
    concerns = f" | Concerns: {', '.join(p.concerns)}" if p.concerns else ""
    url = f" (URL: {p.url})" if include_url and p.url else ""
    return f"- **{p.name}**{risk_tag}{category}: {p.purpose}{data}{concerns}{url}"


def _build_score_lines(
    score_breakdown: analysis.ScoreBreakdown,
) -> list[str]:
    """Build deterministic privacy-score lines.

    Args:
        score_breakdown: Pre-computed privacy score.

    Returns:
        List of lines.
    """
    label = risk.risk_label(score_breakdown.total_score)
    top = ", ".join(score_breakdown.factors[:5]) or "none"
    cat_lines = "\n".join(f"- {name}: {cat.points}/{cat.max_points}" for name, cat in score_breakdown.categories.items() if cat.points > 0)
    return [
        "",
        "## Deterministic Privacy Score",
        f"Score: {score_breakdown.total_score}/100 ({label})",
        f"Top factors: {top}",
        "",
        "Category breakdown:",
        cat_lines,
        "",
        "Your risk assessments MUST be consistent with this score.",
    ]
