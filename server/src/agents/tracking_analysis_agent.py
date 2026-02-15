"""Tracking analysis agent for privacy risk assessment.

Generates a comprehensive markdown privacy report by
analysing cookies, scripts, network requests, and storage
data.  Supports both full-response and streaming modes.
"""

from __future__ import annotations

import json

import agent_framework

from src.agents import base, config
from src.agents.prompts import tracking_analysis
from src.data import loader
from src.models import analysis, consent
from src.utils import logger

log = logger.create_logger("TrackingAnalysisAgent")


# ── Agent class ─────────────────────────────────────────────────


class TrackingAnalysisAgent(base.BaseAgent):
    """Text agent that generates privacy analysis reports.

    Does NOT use structured output — the response is
    free-form markdown.  Supports streaming via
    ``analyze_stream()``.
    """

    agent_name = config.AGENT_TRACKING_ANALYSIS
    instructions = tracking_analysis.INSTRUCTIONS
    max_tokens = 4096
    max_retries = 5
    response_model = None  # Free-form markdown output

    async def analyze_stream(
        self,
        tracking_summary: analysis.TrackingSummary,
        consent_details: consent.ConsentDetails | None = None,
        pre_consent_stats: analysis.PreConsentStats | None = None,
    ):
        """Stream the tracking analysis token-by-token.

        Yields ``AgentResponseUpdate`` objects whose ``.text``
        attribute contains the incremental text delta.

        Args:
            tracking_summary: Collected tracking data summary.
            consent_details: Optional consent dialog info.
            pre_consent_stats: Optional pre-consent page-load stats.

        Yields:
            ``AgentResponseUpdate`` with text deltas.
        """
        prompt = _build_user_prompt(tracking_summary, consent_details, pre_consent_stats)
        log.info(
            "Starting streaming tracking analysis",
            {
                "promptChars": len(prompt),
                "hasConsent": consent_details is not None,
            },
        )
        message = agent_framework.ChatMessage(
            role=agent_framework.Role.USER,
            text=prompt,
        )
        chunk_count = 0
        async with self._build_agent() as agent:
            async for update in agent.run_stream(message):
                chunk_count += 1
                yield update
        log.info(
            "Streaming tracking analysis complete",
            {
                "chunks": chunk_count,
            },
        )


# ── Prompt builders ─────────────────────────────────────────────


def _build_user_prompt(
    tracking_summary: analysis.TrackingSummary,
    consent_details: consent.ConsentDetails | None = None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
) -> str:
    """Build the user prompt from tracking data.

    Args:
        tracking_summary: Collected tracking data summary.
        consent_details: Optional consent dialog info.
        pre_consent_stats: Optional pre-consent page-load stats.

    Returns:
        Formatted user prompt string.
    """
    consent_section = ""
    if consent_details and (consent_details.categories or consent_details.partners or consent_details.claimed_partner_count):
        consent_section = _build_consent_section(consent_details)

    breakdown = json.dumps(
        [d.model_dump() for d in tracking_summary.domain_breakdown],
        indent=2,
    )
    local_json = json.dumps(tracking_summary.local_storage, indent=2)
    session_json = json.dumps(tracking_summary.session_storage, indent=2)

    pre_consent_section = ""
    if pre_consent_stats:
        pre_consent_section = _build_pre_consent_section(pre_consent_stats)

    return (
        "Analyze the following tracking data collected"
        f" from: {tracking_summary.analyzed_url}\n\n"
        "## Summary\n"
        f"- Total Cookies: {tracking_summary.total_cookies}\n"
        "- Total Scripts:"
        f" {tracking_summary.total_scripts}\n"
        "- Total Network Requests:"
        f" {tracking_summary.total_network_requests}\n"
        "- LocalStorage Items:"
        f" {tracking_summary.local_storage_items}\n"
        "- SessionStorage Items:"
        f" {tracking_summary.session_storage_items}\n"
        "- Third-Party Domains:"
        f" {len(tracking_summary.third_party_domains)}\n\n"
        "## Third-Party Domains Detected\n"
        f"{chr(10).join(tracking_summary.third_party_domains)}"
        "\n\n## Domain Breakdown\n"
        f"{breakdown}\n\n"
        f"## LocalStorage Data\n{local_json}\n\n"
        f"## SessionStorage Data\n{session_json}"
        f"{pre_consent_section}"
        f"{consent_section}\n\n"
        f"{_build_gdpr_reference()}\n\n"
        f"{loader.build_media_group_context(tracking_summary.analyzed_url)}\n\n"
        "Please provide a comprehensive privacy analysis"
        " of this tracking data. If consent dialog"
        " information is provided, compare what was"
        " disclosed to users vs what is actually happening,"
        " and highlight any concerning discrepancies."
        " If publisher/media group context is provided,"
        " cross-reference observed activity against"
        " known vendors and privacy characteristics."
    )


def _build_consent_section(
    cd: consent.ConsentDetails,
) -> str:
    """Build the consent information section.

    Args:
        cd: Consent details from the dialog.

    Returns:
        Formatted markdown section.
    """
    cats = (
        "\n".join(f"- **{c.name}** ({'Required' if c.required else 'Optional'}): {c.description}" for c in cd.categories)
        if cd.categories
        else "No categories found"
    )

    partners = "\n".join(_format_partner(p) for p in cd.partners) if cd.partners else "No partners listed"

    purposes = "\n".join(f"- {p}" for p in cd.purposes) if cd.purposes else "No specific purposes listed"

    # Include the claimed partner count so the LLM knows
    # how many partners the dialog says it has, even when
    # individual partners were not extracted.
    claimed_line = ""
    if cd.claimed_partner_count:
        claimed_line = f"\n\n### Claimed Partner Count: {cd.claimed_partner_count}"

    return (
        "\n\n## Cookie Consent Dialog Information"
        " (What Users Agreed To)\n\n"
        f"### Cookie Categories Disclosed\n{cats}\n\n"
        "### Partners/Vendors Listed"
        f" ({len(cd.partners)} found)\n{partners}"
        f"{claimed_line}\n\n"
        f"### Stated Purposes\n{purposes}\n\n"
        "### Raw Consent Text Excerpts\n"
        f"{cd.raw_text[:3000]}"
    )


def _build_pre_consent_section(
    stats: analysis.PreConsentStats,
) -> str:
    """Build the pre-consent page-load activity section.

    Args:
        stats: Pre-consent statistics snapshot.

    Returns:
        Formatted markdown section.
    """
    return (
        "\n\n## Activity on Initial Page Load"
        " (before any dialogs were dismissed)\n"
        "NOTE: This is what was present when the page first loaded. "
        "We cannot confirm whether these scripts use the cookies listed, "
        "whether any dialog is a consent dialog, or whether this activity "
        "falls within the scope of what the user is asked to consent to.\n"
        f"- Cookies on load: {stats.total_cookies}"
        f" ({stats.tracking_cookies} matched tracking patterns)\n"
        f"- Scripts on load: {stats.total_scripts}"
        f" ({stats.tracking_scripts} matched tracking patterns)\n"
        f"- Requests on load: {stats.total_requests}"
        f" ({stats.tracker_requests} matched tracking patterns)"
    )


def _format_partner(p: consent.ConsentPartner) -> str:
    """Format a single partner for the prompt.

    Args:
        p: Consent partner to format.

    Returns:
        Formatted markdown line.
    """
    risk = f" [{p.risk_level.upper()} RISK]" if p.risk_level else ""
    category = f" ({p.risk_category})" if p.risk_category else ""
    data = f" | Data: {', '.join(p.data_collected)}" if p.data_collected else ""
    concerns = f" | Concerns: {', '.join(p.concerns)}" if p.concerns else ""
    return f"- **{p.name}**{risk}{category}: {p.purpose}{data}{concerns}"


def _build_gdpr_reference() -> str:
    """Build a GDPR/TCF reference for the user prompt.

    Provides the LLM with TCF purpose names, known
    consent-state cookie names, GDPR lawful bases, and
    ePrivacy cookie categories so it can produce informed
    and accurate analysis.

    Returns:
        Formatted reference section string.
    """
    lines: list[str] = ["## GDPR / TCF Reference"]

    # TCF purpose names with risk levels.
    tcf = loader.get_tcf_purposes()
    purposes = tcf.get("purposes", {})
    if purposes:
        lines.append("")
        lines.append("### IAB TCF v2.2 Purposes")
        for pid, entry in sorted(purposes.items(), key=lambda x: int(x[0])):
            risk_level = entry.get("risk_level", "")
            lines.append(f"- Purpose {pid}: {entry['name']} (risk: {risk_level})")

    # Special features (high privacy risk).
    special_features = tcf.get("special_features", {})
    if special_features:
        lines.append("")
        lines.append("### TCF Special Features (require explicit consent)")
        for sfid, entry in sorted(special_features.items(), key=lambda x: int(x[0])):
            lines.append(f"- SF {sfid}: {entry['name']}")

    # Consent cookie names so the LLM distinguishes them
    # from tracking cookies.
    consent_data = loader.get_consent_cookies()
    tcf_cookies = consent_data.get("tcf_cookies", {})
    cmp_cookies = consent_data.get("cmp_cookies", {})
    if tcf_cookies or cmp_cookies:
        lines.append("")
        lines.append("### Known Consent-State Cookies")
        lines.append(
            "These cookies store user consent preferences and should be classified as 'Functional / Necessary', NOT as tracking cookies:"
        )
        for name, info in tcf_cookies.items():
            if name.startswith("__"):
                continue  # Skip __tcfapi (it's a JS API, not a cookie)
            lines.append(f"- {name}: {info['description']}")
        for name, info in cmp_cookies.items():
            lines.append(f"- {name}: {info['description']}")

    # GDPR lawful bases (compact summary for consent evaluation).
    gdpr = loader.get_gdpr_reference()
    lawful_bases = gdpr.get("gdpr", {}).get("lawful_bases", {})
    if lawful_bases:
        lines.append("")
        lines.append("### GDPR Lawful Bases for Processing")
        for basis_key, basis in lawful_bases.items():
            article = basis.get("article", "")
            desc = basis.get("description", "")
            lines.append(f"- {basis_key} ({article}): {desc}")

    # ePrivacy cookie categories.
    cookie_cats = gdpr.get("eprivacy_directive", {}).get("cookie_categories", {})
    if cookie_cats:
        lines.append("")
        lines.append("### ePrivacy Cookie Categories")
        for cat_key, cat in cookie_cats.items():
            consent_req = "consent required" if cat.get("consent_required") else "no consent required"
            lines.append(f"- {cat_key}: {cat['description']} ({consent_req})")

    return "\n".join(lines)
