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

import dataclasses
import json
from typing import TYPE_CHECKING

from src.agents import gdpr_context
from src.analysis import domain_cache
from src.data import loader
from src.models import analysis, consent
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


# Per-section configs derived from the needs-matrix audit.
# Each entry maps a report section name to the minimal set
# of context blocks it requires.

SECTION_CONFIGS: dict[str, SectionNeeds] = {
    "tracking-technologies": SectionNeeds(
        third_party_domains=True,
        domain_breakdown=True,
        local_storage=True,
        session_storage=True,
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
        domain_knowledge=True,
        gdpr_reference=True,
        tracking_cookie_db=True,
        disconnect_db=True,
        include_partner_urls=True,
    ),
    "social-media-implications": SectionNeeds(
        third_party_domains=True,
        domain_breakdown=True,
        domain_knowledge=True,
        tracking_cookie_db=True,
        disconnect_db=True,
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


def build_section_context(
    section_name: str,
    tracking_summary: analysis.TrackingSummary,
    *,
    consent_details: consent.ConsentDetails | None = None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
    score_breakdown: analysis.ScoreBreakdown | None = None,
    domain_knowledge: domain_cache.DomainKnowledge | None = None,
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
                "## Third-Party Domains",
                "\n".join(tracking_summary.third_party_domains),
            ]
        )

    if needs.domain_breakdown:
        breakdown = json.dumps(
            [d.model_dump(exclude_defaults=True) for d in tracking_summary.domain_breakdown],
        )
        sections.extend(
            [
                "",
                "## Domain Breakdown (cookies, scripts, requests per domain)",
                breakdown,
            ]
        )

    if needs.local_storage:
        local_json = json.dumps(tracking_summary.local_storage)
        sections.extend(["", f"## LocalStorage Data\n{local_json}"])

    if needs.session_storage:
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
