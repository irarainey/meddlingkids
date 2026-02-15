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
    ):
        """Stream the tracking analysis token-by-token.

        Yields ``AgentResponseUpdate`` objects whose ``.text``
        attribute contains the incremental text delta.

        Args:
            tracking_summary: Collected tracking data summary.
            consent_details: Optional consent dialog info.

        Yields:
            ``AgentResponseUpdate`` with text deltas.
        """
        prompt = _build_user_prompt(tracking_summary, consent_details)
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
) -> str:
    """Build the user prompt from tracking data.

    Args:
        tracking_summary: Collected tracking data summary.
        consent_details: Optional consent dialog info.

    Returns:
        Formatted user prompt string.
    """
    consent_section = ""
    if consent_details and (consent_details.categories or consent_details.partners):
        consent_section = _build_consent_section(consent_details)

    breakdown = json.dumps(
        [d.model_dump() for d in tracking_summary.domain_breakdown],
        indent=2,
    )
    local_json = json.dumps(tracking_summary.local_storage, indent=2)
    session_json = json.dumps(tracking_summary.session_storage, indent=2)

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

    return (
        "\n\n## Cookie Consent Dialog Information"
        " (What Users Agreed To)\n\n"
        f"### Cookie Categories Disclosed\n{cats}\n\n"
        "### Partners/Vendors Listed"
        f" ({len(cd.partners)} found)\n{partners}\n\n"
        f"### Stated Purposes\n{purposes}\n\n"
        "### Raw Consent Text Excerpts\n"
        f"{cd.raw_text[:3000]}"
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
    """Build a compact GDPR/TCF reference for the user prompt.

    Provides the LLM with TCF purpose names and known
    consent-state cookie names so it can produce more
    informed and accurate analysis.

    Returns:
        Formatted reference section string.
    """
    lines: list[str] = ["## GDPR / TCF Reference"]

    tcf = loader.get_tcf_purposes()
    purposes = tcf.get("purposes", {})
    if purposes:
        lines.append("")
        lines.append("### IAB TCF v2.2 Purposes")
        for pid, entry in sorted(purposes.items(), key=lambda x: int(x[0])):
            lines.append(f"- Purpose {pid}: {entry['name']}")

    # Consent cookie names so the LLM distinguishes them
    # from tracking cookies.
    consent_data = loader.get_consent_cookies()
    all_cookies: list[str] = []
    for name in consent_data.get("tcf_cookies", {}):
        if not name.startswith("__"):
            all_cookies.append(name)
    all_cookies.extend(consent_data.get("cmp_cookies", {}))
    if all_cookies:
        lines.append("")
        lines.append("### Known Consent-State Cookies")
        lines.append("These store user consent preferences (functional, not tracking): " + ", ".join(all_cookies))

    return "\n".join(lines)
