"""Tracking analysis agent for privacy risk assessment.

Generates a comprehensive markdown privacy report by
analysing cookies, scripts, network requests, and storage
data.  Supports both full-response and streaming modes.
"""

from __future__ import annotations

import json

import agent_framework

from src.agents.base import BaseAgent
from src.agents.config import AGENT_TRACKING_ANALYSIS
from src.types.analysis import TrackingSummary
from src.types.consent import (
    ConsentDetails,
    ConsentPartner,
)
from src.utils import logger

log = logger.create_logger("TrackingAnalysisAgent")


# ── System prompt ───────────────────────────────────────────────

_INSTRUCTIONS = """\
You are a privacy and web tracking expert analyst. Your task \
is to analyze tracking data collected from a website and \
provide comprehensive insights about:

1. **Tracking Technologies Identified**: Identify known \
tracking services (Google Analytics, Facebook Pixel, \
advertising networks, etc.) based on cookie names, script \
URLs, and network requests.

2. **Data Collection Analysis**: What types of data are \
likely being collected (browsing behavior, user \
identification, cross-site tracking, etc.)

3. **Third-Party Services**: List each third-party domain \
found and explain what company/service it belongs to and \
what they typically track.

4. **Privacy Risk Assessment**: Rate the privacy risk level \
(Low/Medium/High/Very High) and explain why.

5. **Cookie Analysis**: Analyse cookie purposes — which are \
functional, which are for tracking, and their persistence.

6. **Storage Analysis**: Analyse localStorage/sessionStorage \
usage and what data might be persisted.

7. **Consent Dialog Analysis**: If consent information is \
provided, analyse what the website disclosed about tracking \
and compare it to what was actually detected.  Highlight \
any discrepancies or concerning practices.

8. **Partner/Vendor Analysis**: If partner information is \
provided, explain what each partner does, what data they \
collect, and the privacy implications.

9. **Recommendations**: What users can do to protect their \
privacy on this site.

Format your response in clear sections with markdown \
headings. Be specific about which domains and cookies you \
are referring to. If you recognise specific tracking \
technologies, name them explicitly.

IMPORTANT: Pay special attention to the consent dialog \
information if provided — this is what users typically \
do not read but agree to. Highlight the most concerning \
aspects."""


# ── Agent class ─────────────────────────────────────────────────

class TrackingAnalysisAgent(BaseAgent):
    """Text agent that generates privacy analysis reports.

    Does NOT use structured output — the response is
    free-form markdown.  Supports streaming via
    ``analyze_stream()``.
    """

    agent_name = AGENT_TRACKING_ANALYSIS
    instructions = _INSTRUCTIONS
    max_tokens = 3000
    max_retries = 3
    response_model = None  # Free-form markdown output

    async def analyze(
        self,
        tracking_summary: TrackingSummary,
        consent_details: ConsentDetails | None = None,
    ) -> str:
        """Run the full tracking analysis (non-streaming).

        Args:
            tracking_summary: Collected tracking data summary.
            consent_details: Optional consent dialog info.

        Returns:
            Markdown analysis text.
        """
        prompt = _build_user_prompt(
            tracking_summary, consent_details
        )
        response = await self._complete(prompt)
        return response.text or "No analysis generated"

    async def analyze_stream(
        self,
        tracking_summary: TrackingSummary,
        consent_details: ConsentDetails | None = None,
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
        prompt = _build_user_prompt(
            tracking_summary, consent_details
        )
        message = agent_framework.ChatMessage(
            role=agent_framework.Role.USER,
            text=prompt,
        )
        async with self._build_agent() as agent:
            async for update in agent.run_stream(message):
                yield update


# ── Prompt builders ─────────────────────────────────────────────

def _build_user_prompt(
    tracking_summary: TrackingSummary,
    consent_details: ConsentDetails | None = None,
) -> str:
    """Build the user prompt from tracking data.

    Args:
        tracking_summary: Collected tracking data summary.
        consent_details: Optional consent dialog info.

    Returns:
        Formatted user prompt string.
    """
    consent_section = ""
    if consent_details and (
        consent_details.categories
        or consent_details.partners
    ):
        consent_section = _build_consent_section(
            consent_details
        )

    breakdown = json.dumps(
        [
            d.model_dump()
            for d in tracking_summary.domain_breakdown
        ],
        indent=2,
    )
    local_json = json.dumps(
        tracking_summary.local_storage, indent=2
    )
    session_json = json.dumps(
        tracking_summary.session_storage, indent=2
    )

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
        "Please provide a comprehensive privacy analysis"
        " of this tracking data. If consent dialog"
        " information is provided, compare what was"
        " disclosed to users vs what is actually happening,"
        " and highlight any concerning discrepancies."
    )


def _build_consent_section(
    cd: ConsentDetails,
) -> str:
    """Build the consent information section.

    Args:
        cd: Consent details from the dialog.

    Returns:
        Formatted markdown section.
    """
    cats = (
        "\n".join(
            f"- **{c.name}**"
            f" ({'Required' if c.required else 'Optional'}):"
            f" {c.description}"
            for c in cd.categories
        )
        if cd.categories
        else "No categories found"
    )

    partners = (
        "\n".join(
            _format_partner(p) for p in cd.partners
        )
        if cd.partners
        else "No partners listed"
    )

    purposes = (
        "\n".join(f"- {p}" for p in cd.purposes)
        if cd.purposes
        else "No specific purposes listed"
    )

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


def _format_partner(p: ConsentPartner) -> str:
    """Format a single partner for the prompt.

    Args:
        p: Consent partner to format.

    Returns:
        Formatted markdown line.
    """
    risk = (
        f" [{p.risk_level.upper()} RISK]"
        if p.risk_level
        else ""
    )
    category = (
        f" ({p.risk_category})" if p.risk_category else ""
    )
    data = (
        f" | Data: {', '.join(p.data_collected)}"
        if p.data_collected
        else ""
    )
    concerns = (
        f" | Concerns: {', '.join(p.concerns)}"
        if p.concerns
        else ""
    )
    return (
        f"- **{p.name}**{risk}{category}:"
        f" {p.purpose}{data}{concerns}"
    )
