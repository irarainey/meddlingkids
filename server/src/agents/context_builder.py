"""Shared context builder for LLM analysis prompts.

Both the tracking-analysis agent and the structured-report agent
require the same core data sections (summary stats, consent block,
score block, GDPR reference, domain-knowledge hint, etc.). This
module centralises that context assembly so the overlapping sections
are defined in one place.
"""

from __future__ import annotations

import json

from src.agents import gdpr_context
from src.analysis import domain_cache
from src.data import loader
from src.models import analysis, consent
from src.utils import risk

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
    breakdown = json.dumps(
        [d.model_dump(exclude_defaults=True) for d in tracking_summary.domain_breakdown],
    )
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
            "## Third-Party Domains",
            "\n".join(tracking_summary.third_party_domains),
            "",
            "## Domain Breakdown (cookies, scripts, requests per domain)",
            breakdown,
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

    sections.append(
        "\n"
        + gdpr_context.build_gdpr_reference(
            heading="## GDPR / TCF Reference Data",
        ),
    )

    cookie_ctx = loader.build_tracking_cookie_context()
    if cookie_ctx:
        sections.append(cookie_ctx)

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

    return "\n".join(sections)


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
