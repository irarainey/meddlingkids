"""
Tracking analysis prompts for privacy risk assessment.
Contains system prompts and user prompt builders for LLM-based analysis.
"""

from __future__ import annotations

from src.types.tracking import ConsentDetails, TrackingSummary
from dataclasses import asdict
import json

TRACKING_ANALYSIS_SYSTEM_PROMPT = """You are a privacy and web tracking expert analyst. Your task is to analyze tracking data collected from a website and provide comprehensive insights about:

1. **Tracking Technologies Identified**: Identify known tracking services (Google Analytics, Facebook Pixel, advertising networks, etc.) based on cookie names, script URLs, and network requests.

2. **Data Collection Analysis**: What types of data are likely being collected (browsing behavior, user identification, cross-site tracking, etc.)

3. **Third-Party Services**: List each third-party domain found and explain what company/service it belongs to and what they typically track.

4. **Privacy Risk Assessment**: Rate the privacy risk level (Low/Medium/High/Very High) and explain why.

5. **Cookie Analysis**: Analyze cookie purposes - which are functional, which are for tracking, and their persistence.

6. **Storage Analysis**: Analyze localStorage/sessionStorage usage and what data might be persisted.

7. **Consent Dialog Analysis**: If consent information is provided, analyze what the website disclosed about tracking and compare it to what was actually detected. Highlight any discrepancies or concerning practices.

8. **Partner/Vendor Analysis**: If partner information is provided, explain what each partner does, what data they collect, and the privacy implications.

9. **Recommendations**: What users can do to protect their privacy on this site.

Format your response in clear sections with markdown headings. Be specific about which domains and cookies you're referring to. If you recognize specific tracking technologies, name them explicitly.

IMPORTANT: Pay special attention to the consent dialog information if provided - this is what users typically don't read but agree to. Highlight the most concerning aspects."""


SUMMARY_FINDINGS_SYSTEM_PROMPT = """You are a privacy expert. Analyze the tracking data and create a structured summary of the key findings.

Return a JSON array of findings. Each finding should have:
- "type": One of "critical", "high", "moderate", "info", "positive"
- "text": A single sentence describing the finding. Be specific about company names.

Types explained:
- "critical": Cross-site tracking, fingerprinting, data selling, deceptive practices
- "high": Persistent tracking, third-party data sharing, advertising networks
- "moderate": Standard analytics, typical ad tracking
- "info": General information about cookies or consent
- "positive": Privacy-respecting practices, minimal tracking, good practices

Return 5-7 findings maximum, ordered by severity (critical first, positive last).

You MUST respond with ONLY valid JSON array, no other text. Example:
[
  {"type": "critical", "text": "Facebook Pixel tracks your activity across multiple websites."},
  {"type": "high", "text": "Google Analytics collects detailed browsing behavior."},
  {"type": "positive", "text": "Site uses secure HTTPS-only cookies."}
]"""


PRIVACY_SCORE_SYSTEM_PROMPT = """You are a privacy expert. Based on a tracking analysis, provide a privacy risk score from 0-100 and a one-sentence summary.

Scoring guidelines:
- 80-100: Critical risk - extensive cross-site tracking, fingerprinting, data selling to many partners, deceptive practices
- 60-79: High risk - significant third-party tracking, multiple advertising networks, questionable data sharing
- 40-59: Moderate risk - standard analytics, some third-party trackers, typical advertising
- 20-39: Low risk - minimal tracking, basic analytics only, few third parties
- 0-19: Very low risk - privacy-respecting, minimal or no tracking, first-party only

IMPORTANT: The summary MUST start with the site name (e.g., "bbc.com has...", "amazon.co.uk uses...").

You MUST respond with ONLY valid JSON in this exact format, no other text:
{"score": <number 0-100>, "summary": "<site name in lowercase> <one sentence about key findings>"}"""


def _build_consent_section(consent_details: ConsentDetails) -> str:
    """Build the consent information section for the analysis prompt."""
    categories_text = (
        "\n".join(
            f"- **{c.name}** ({'Required' if c.required else 'Optional'}): {c.description}"
            for c in consent_details.categories
        )
        if consent_details.categories
        else "No categories found"
    )

    partners_text = (
        "\n".join(
            _format_partner(p) for p in consent_details.partners
        )
        if consent_details.partners
        else "No partners listed"
    )

    purposes_text = (
        "\n".join(f"- {p}" for p in consent_details.purposes)
        if consent_details.purposes
        else "No specific purposes listed"
    )

    return f"""

## Cookie Consent Dialog Information (What Users Agreed To)

### Cookie Categories Disclosed
{categories_text}

### Partners/Vendors Listed ({len(consent_details.partners)} found)
{partners_text}

### Stated Purposes
{purposes_text}

### Raw Consent Text Excerpts
{consent_details.raw_text[:3000]}
"""


def _format_partner(p: object) -> str:
    """Format a single partner for the prompt."""
    from src.types.tracking import ConsentPartner

    if not isinstance(p, ConsentPartner):
        return str(p)
    risk = f" [{p.risk_level.upper()} RISK]" if p.risk_level else ""
    category = f" ({p.risk_category})" if p.risk_category else ""
    data = f" | Data: {', '.join(p.data_collected)}" if p.data_collected else ""
    concerns = f" | Concerns: {', '.join(p.concerns)}" if p.concerns else ""
    return f"- **{p.name}**{risk}{category}: {p.purpose}{data}{concerns}"


def build_tracking_analysis_user_prompt(
    tracking_summary: TrackingSummary,
    consent_details: ConsentDetails | None = None,
) -> str:
    """Build the user prompt for tracking analysis."""
    consent_section = ""
    if consent_details and (consent_details.categories or consent_details.partners):
        consent_section = _build_consent_section(consent_details)

    breakdown = json.dumps(
        [asdict(d) for d in tracking_summary.domain_breakdown], indent=2
    )
    local_storage_json = json.dumps(tracking_summary.local_storage, indent=2)
    session_storage_json = json.dumps(tracking_summary.session_storage, indent=2)

    return f"""Analyze the following tracking data collected from: {tracking_summary.analyzed_url}

## Summary
- Total Cookies: {tracking_summary.total_cookies}
- Total Scripts: {tracking_summary.total_scripts}
- Total Network Requests: {tracking_summary.total_network_requests}
- LocalStorage Items: {tracking_summary.local_storage_items}
- SessionStorage Items: {tracking_summary.session_storage_items}
- Third-Party Domains: {len(tracking_summary.third_party_domains)}

## Third-Party Domains Detected
{chr(10).join(tracking_summary.third_party_domains)}

## Domain Breakdown
{breakdown}

## LocalStorage Data
{local_storage_json}

## SessionStorage Data
{session_storage_json}
{consent_section}

Please provide a comprehensive privacy analysis of this tracking data. If consent dialog information is provided, compare what was disclosed to users vs what is actually happening, and highlight any concerning discrepancies."""


def build_summary_findings_user_prompt(analysis: str) -> str:
    """Build the user prompt for summary findings generation."""
    return f"Based on this full analysis, create a structured JSON array of key findings:\n\n{analysis}"


def build_privacy_score_user_prompt(analysis: str, site_url: str) -> str:
    """Build the user prompt for privacy score generation."""
    from urllib.parse import urlparse

    try:
        hostname = urlparse(site_url).hostname or site_url
        site_name = hostname.removeprefix("www.").lower()
    except Exception:
        site_name = site_url.lower()

    return (
        f"Site analyzed: {site_name}\n\n"
        "Based on this tracking analysis, provide a privacy risk score (0-100) and "
        "one-sentence summary that starts with the site name. Respond with JSON only:\n\n"
        f"{analysis}"
    )
