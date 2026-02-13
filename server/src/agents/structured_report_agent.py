"""Structured report agent for deterministic privacy reports.

Makes focused LLM calls for each report section, producing
structured JSON output rather than free-form markdown. Each
section gets its own system prompt and response schema to
ensure consistent, professional output.
"""

from __future__ import annotations

import asyncio
import json
from typing import TypeVar

import pydantic

from src.agents import base
from src.models import analysis, consent
from src.models import report as report_models  # type: ignore[attr-defined]
from src.utils import json_parsing, logger

log = logger.create_logger("StructuredReportAgent")


# ── Helpers ─────────────────────────────────────────────────────


def _risk_label(score: int) -> str:
    """Map a 0-100 score to a human risk label."""
    if score >= 80:
        return "Critical Risk"
    if score >= 60:
        return "High Risk"
    if score >= 40:
        return "Moderate Risk"
    if score >= 20:
        return "Low Risk"
    return "Very Low Risk"


# ── Agent name ──────────────────────────────────────────────────

AGENT_NAME = "StructuredReportAgent"


# ── Per-section response wrappers ───────────────────────────────
# Each wrapper is a simple Pydantic model that the LLM fills
# via ``response_format``.  The agent swaps the wrapper for
# each section call.

class _TrackingTechResponse(pydantic.BaseModel):
    section: report_models.TrackingTechnologiesSection


class _DataCollectionResponse(pydantic.BaseModel):
    section: report_models.DataCollectionSection


class _ThirdPartyResponse(pydantic.BaseModel):
    section: report_models.ThirdPartySection


class _PrivacyRiskResponse(pydantic.BaseModel):
    section: report_models.PrivacyRiskSection


class _CookieAnalysisResponse(pydantic.BaseModel):
    section: report_models.CookieAnalysisSection


class _StorageAnalysisResponse(pydantic.BaseModel):
    section: report_models.StorageAnalysisSection


class _ConsentAnalysisResponse(pydantic.BaseModel):
    section: report_models.ConsentAnalysisSection


class _VendorResponse(pydantic.BaseModel):
    section: report_models.VendorSection


class _RecommendationsResponse(pydantic.BaseModel):
    section: report_models.RecommendationsSection


# ── Section prompts ─────────────────────────────────────────────

_TRACKING_TECH_PROMPT = """\
You are a privacy expert. Analyse the tracking data and identify \
all tracking technologies present on the page.

Categorise each tracker into one of these groups:
- analytics: Analytics and measurement platforms (e.g. Google Analytics, Chartbeat)
- advertising: Advertising networks, DSPs, SSPs, RTB platforms
- identity_resolution: Identity resolution, cookie-sync, cross-site ID systems (e.g. ID5, LiveRamp)
- social_media: Social media tracking pixels and integrations
- other: Any other tracking technology

For each tracker provide:
- name: The company or service name
- domains: List of domains associated with this tracker
- cookies: List of cookie names set by this tracker (if any)
- storage_keys: List of localStorage/sessionStorage keys used (if any)
- purpose: One-sentence description of what it does

Be specific and factual. Only list trackers you can confirm from the data provided. \
Do NOT invent trackers not evidenced by the data."""

_DATA_COLLECTION_PROMPT = """\
You are a privacy expert. Based on the tracking data, identify what types of data \
are being collected from users.

For each data type provide:
- category: Short label (e.g. "Browsing Behaviour", "Device Information", \
"Location Data", "User Identity", "Financial / Payment", "Health & Wellness")
- details: List of specific data points collected
- risk: Risk level — "low", "medium", "high", or "critical"
- sensitive: true if the data is personal or sensitive (e.g. precise location, \
health information, financial data, biometric identifiers, racial/ethnic origin, \
political opinions, religious beliefs, sexual orientation, or any data that \
could directly identify an individual such as email, name, phone number, \
government ID). Otherwise false.
- shared_with: List of third-party company or service names this data \
is sent to or shared with, based on the network requests and domains observed. \
Leave empty if the data stays first-party only.

Pay special attention to:
- Precise geolocation or IP-based location shared with ad networks
- User identifiers (email hashes, phone hashes, login IDs) sent to \
identity resolution or data broker services
- Browsing/search history shared across multiple third-party domains
- Device fingerprinting data (canvas, WebGL, audio context) collected \
by tracking scripts
- Any POST request payloads containing personal data

Focus on factual observations from the cookies, scripts, storage, and network \
requests provided. Be specific about which cookies, storage keys, or network \
requests indicate each type of data collection and sharing."""

_THIRD_PARTY_PROMPT = """\
You are a privacy expert. Categorise the third-party domains contacted by this page.

Provide:
- total_domains: Total number of third-party domains
- groups: Categorised groups, each with:
  - category: Group label (e.g. "Ad Exchanges / SSPs", "Identity & Data Brokers", "Measurement")
  - services: List of company or service names in this group
  - privacy_impact: One-sentence impact statement
- summary: One-sentence overall summary

Focus on the most significant domains. Group similar services together."""

_PRIVACY_RISK_PROMPT = """\
You are a privacy expert. Provide an overall privacy risk assessment.

You will be given the site's deterministic privacy score (0–100) \
and its risk classification. Your overall_risk MUST be consistent \
with this score:
- Score 0–19  (Very Low Risk)  → overall_risk = "low"
- Score 20–39 (Low Risk)       → overall_risk = "low"
- Score 40–59 (Moderate Risk)  → overall_risk = "medium"
- Score 60–79 (High Risk)      → overall_risk = "high"
- Score 80–100 (Critical Risk) → overall_risk = "very-high"

List the specific factors that contribute to this risk level, each with:
- description: What the factor is
- severity: "low", "medium", "high", or "critical"

Individual factors can have higher severity than the overall risk \
when a specific practice is genuinely concerning, but the overall_risk \
must align with the deterministic score above.

Provide a concise summary explaining the overall risk assessment.

Base your assessment strictly on the data provided — number of trackers, \
third-party domains, cookie persistence, identity systems, data broker \
involvement, network request volume, and pre-consent tracking activity."""

_COOKIE_ANALYSIS_PROMPT = """\
You are a privacy expert. Analyse the cookies found on this page.

Provide:
- total: Total number of cookies
- groups: Grouped by purpose, each with:
  - category: Purpose label (e.g. "Functional / Necessary", "Analytics", "Advertising & Tracking")
  - cookies: List of cookie names in this group
  - lifespan: Typical lifespan description
  - concern_level: "none", "low", "medium", or "high"
- concerning_cookies: List of the most concerning individual cookies with brief reasons

Only classify cookies you can identify from their names and domains."""

_STORAGE_ANALYSIS_PROMPT = """\
You are a privacy expert. Analyse the localStorage and sessionStorage usage.

Provide:
- local_storage_count: Number of localStorage items
- session_storage_count: Number of sessionStorage items
- local_storage_concerns: List of concerning localStorage observations
- session_storage_concerns: List of concerning sessionStorage observations
- summary: One-sentence overall assessment

Focus on items that indicate tracking, identity persistence, or \
behavioural profiling. Mention specific key names where relevant."""

_CONSENT_ANALYSIS_PROMPT = """\
You are a privacy expert. Compare the consent dialog disclosures with \
the actual tracking detected on the page.

Provide:
- has_consent_dialog: Whether a consent dialog was detected
- categories_disclosed: Number of consent categories shown to users
- partners_disclosed: Number of partners/vendors disclosed. Use the \
claimed partner count from the consent dialog text if available \
(e.g. "We and our 1467 partners"), as this is the number the site \
claims to share data with, even if individual partner names were \
not extracted.
- discrepancies: List of discrepancies between claims and reality, each with:
  - claimed: What the consent dialog says
  - actual: What was actually detected
  - severity: "low", "medium", "high", or "critical"
- summary: Overall assessment of consent transparency

Severity decision criteria for discrepancies (apply strictly):
- "critical": Consent dialog actively hides or misrepresents tracking \
that violates regulation (e.g. no dialog at all while tracking heavily, \
or dark patterns designed to trick users into accepting).
- "high": Material gap between disclosure and reality, such as \
claiming no third-party sharing while dozens of third-party trackers \
fire, or pre-consent tracking that bypasses user choice entirely.
- "medium": Vague or incomplete disclosure — e.g. consent categories \
are too broad, partner count understated, or cookie descriptions \
are misleading but not deceptive.
- "low": Minor omission or cosmetic mismatch with no material \
privacy impact, such as a slightly outdated partner count.

Be specific and factual. Highlight practices where the actual data \
collection significantly exceeds what is disclosed to users."""

_VENDOR_PROMPT = """\
You are a privacy expert. Identify the most significant vendors/partners \
from a privacy perspective.

List exactly 32 vendors/partners with the highest privacy impact. \
Always return 32 entries unless fewer than 32 distinct vendors exist in the data.
- name: Company name
- role: Their role (e.g. "Analytics", "Retargeting", "Identity resolution")
- privacy_impact: One-sentence privacy impact description

Focus on vendors involved in cross-site tracking, identity resolution, \
data brokerage, retargeting, and extensive data collection. You MUST \
return 32 vendors. Only return fewer if the data genuinely contains \
fewer than 32 distinct vendors."""

_RECOMMENDATIONS_PROMPT = """\
You are a privacy expert. Based on the tracking analysis, provide \
practical recommendations for users visiting this page.

Group recommendations into categories such as:
- "Strongly Recommended": Essential steps most users should take
- "Advanced": Technical steps for privacy-conscious users
- "Best Privacy Option": Strongest protection measures

Each group should have 2-4 actionable items. Be specific and practical."""


# ── Agent class ─────────────────────────────────────────────────

class StructuredReportAgent(base.BaseAgent):
    """Agent that builds structured privacy reports section by section.

    Each section is a separate LLM call with a focused system
    prompt and strict JSON output schema. Sections run
    concurrently where possible for speed.
    """

    agent_name = AGENT_NAME
    instructions = ""  # Overridden per section
    max_tokens = 2048
    max_retries = 5
    response_model = None  # Set dynamically per section

    async def build_report(
        self,
        tracking_summary: analysis.TrackingSummary,
        consent_details: consent.ConsentDetails | None = None,
        pre_consent_stats: analysis.PreConsentStats | None = None,
        score_breakdown: analysis.ScoreBreakdown | None = None,
    ) -> report_models.StructuredReport:
        """Build a complete structured report.

        Runs section LLM calls concurrently in two waves:
        1. Core sections (tracking, data, third-party, cookies,
           storage, risk) — all independent
        2. Derived sections (consent, vendors, recommendations)
           — benefit from earlier context

        Args:
            tracking_summary: Collected tracking data summary.
            consent_details: Optional consent dialog info.
            pre_consent_stats: Optional pre-consent statistics.
            score_breakdown: Deterministic privacy score, if
                available, so the LLM can calibrate risk levels.

        Returns:
            Complete ``StructuredReport``.
        """
        log.start_timer("structured-report")
        context = _build_data_context(
            tracking_summary, consent_details, pre_consent_stats,
            score_breakdown,
        )

        # Wave 1: Core independent sections
        log.info("Building report sections (wave 1)...")
        (
            tracking_tech,
            data_collection,
            third_party,
            cookie_analysis,
            storage_analysis,
            privacy_risk,
        ) = await asyncio.gather(
            self._build_section(
                _TRACKING_TECH_PROMPT,
                context,
                _TrackingTechResponse,
                "tracking-technologies",
            ),
            self._build_section(
                _DATA_COLLECTION_PROMPT,
                context,
                _DataCollectionResponse,
                "data-collection",
            ),
            self._build_section(
                _THIRD_PARTY_PROMPT,
                context,
                _ThirdPartyResponse,
                "third-party-services",
            ),
            self._build_section(
                _COOKIE_ANALYSIS_PROMPT,
                context,
                _CookieAnalysisResponse,
                "cookie-analysis",
            ),
            self._build_section(
                _STORAGE_ANALYSIS_PROMPT,
                context,
                _StorageAnalysisResponse,
                "storage-analysis",
            ),
            self._build_section(
                _PRIVACY_RISK_PROMPT,
                context,
                _PrivacyRiskResponse,
                "privacy-risk",
            ),
        )

        # Wave 2: Sections that benefit from full context
        log.info("Building report sections (wave 2)...")
        consent_section_coro = (
            self._build_section(
                _CONSENT_ANALYSIS_PROMPT,
                context,
                _ConsentAnalysisResponse,
                "consent-analysis",
            )
            if consent_details
            and (consent_details.categories or consent_details.partners
                 or consent_details.claimed_partner_count)
            else _noop_section(report_models.ConsentAnalysisSection())
        )

        vendors, consent_analysis, recommendations = (
            await asyncio.gather(
                self._build_section(
                    _VENDOR_PROMPT,
                    context,
                    _VendorResponse,
                    "key-vendors",
                ),
                consent_section_coro,
                self._build_section(
                    _RECOMMENDATIONS_PROMPT,
                    context,
                    _RecommendationsResponse,
                    "recommendations",
                ),
            )
        )

        # ── Deterministic consent overrides ─────────────────
        # The LLM may miscount or omit consent dialog facts
        # that we already know deterministically.  Override
        # the relevant fields so the report is accurate.
        consent_sec = _extract(
            consent_analysis,
            report_models.ConsentAnalysisSection,
        )
        if consent_details:
            consent_sec.has_consent_dialog = True
            # Use the deterministic category count.
            if consent_details.categories:
                consent_sec.categories_disclosed = len(
                    consent_details.categories
                )
            # Use the claimed partner count from the dialog
            # text (regex-extracted), falling back to the
            # number of individually extracted partners.
            if consent_details.claimed_partner_count:
                consent_sec.partners_disclosed = (
                    consent_details.claimed_partner_count
                )
            elif consent_details.partners:
                consent_sec.partners_disclosed = len(
                    consent_details.partners
                )

        result = report_models.StructuredReport(
            tracking_technologies=_extract(
                tracking_tech,
                report_models.TrackingTechnologiesSection,
            ),
            data_collection=_extract(
                data_collection,
                report_models.DataCollectionSection,
            ),
            third_party_services=_extract(
                third_party,
                report_models.ThirdPartySection,
            ),
            privacy_risk=_extract(
                privacy_risk,
                report_models.PrivacyRiskSection,
            ),
            cookie_analysis=_extract(
                cookie_analysis,
                report_models.CookieAnalysisSection,
            ),
            storage_analysis=_extract(
                storage_analysis,
                report_models.StorageAnalysisSection,
            ),
            consent_analysis=consent_sec,
            key_vendors=_extract(
                vendors,
                report_models.VendorSection,
            ),
            recommendations=_extract(
                recommendations,
                report_models.RecommendationsSection,
            ),
        )

        log.end_timer("structured-report", "Structured report complete")
        return result

    async def _build_section(
        self,
        system_prompt: str,
        data_context: str,
        response_cls: type[pydantic.BaseModel],
        section_name: str,
    ) -> pydantic.BaseModel | None:
        """Build a single report section via LLM.

        Args:
            system_prompt: Section-specific instructions.
            data_context: Formatted tracking data string.
            response_cls: Pydantic response wrapper class.
            section_name: Name for logging.

        Returns:
            Parsed response wrapper, or ``None`` on failure.
        """
        log.start_timer(f"section-{section_name}")
        try:
            response = await self._complete(
                data_context,
                instructions=system_prompt,
                max_tokens=2048,
                response_model=response_cls,
            )

            log.end_timer(
                f"section-{section_name}",
                f"Section '{section_name}' complete",
            )

            # Try structured parse first
            parsed = self._parse_response(response, response_cls)
            if parsed:
                return parsed

            # Fallback: manual JSON parse
            raw = json_parsing.load_json_from_text(response.text)
            if raw:
                try:
                    return response_cls.model_validate(raw)
                except Exception:
                    # Try unwrapping nested "section" key
                    if isinstance(raw, dict) and "section" in raw:
                        return response_cls.model_validate(
                            {"section": raw["section"]}
                        )

            log.warn(f"Section '{section_name}' parse failed")
            return None
        except Exception as err:
            log.error(
                f"Section '{section_name}' failed: {err}"
            )
            return None


async def _noop_section(
    default: pydantic.BaseModel,
) -> pydantic.BaseModel:
    """Return a default section without an LLM call."""
    return default


_ST = TypeVar("_ST", bound=pydantic.BaseModel)


def _extract(
    result: pydantic.BaseModel | None,
    section_cls: type[_ST],
) -> _ST:
    """Extract the section field from a response wrapper.

    Falls back to a default empty instance if parsing failed.

    Args:
        result: Parsed response wrapper (or ``None``).
        section_cls: The section model class.

    Returns:
        Section model instance.
    """
    if result is None:
        return section_cls()
    # Response wrappers have a single "section" field
    section = getattr(result, "section", None)
    if section is not None and isinstance(section, section_cls):
        return section
    # If somehow the result itself is the section type
    if isinstance(result, section_cls):
        return result
    return section_cls()


def _build_data_context(
    tracking_summary: analysis.TrackingSummary,
    consent_details: consent.ConsentDetails | None = None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
    score_breakdown: analysis.ScoreBreakdown | None = None,
) -> str:
    """Build the data context string sent to each section LLM call.

    Args:
        tracking_summary: Collected tracking data summary.
        consent_details: Optional consent dialog info.
        pre_consent_stats: Optional pre-consent statistics.
        score_breakdown: Deterministic privacy score, if
            available.

    Returns:
        Formatted data context string.
    """
    breakdown = json.dumps(
        [d.model_dump() for d in tracking_summary.domain_breakdown],
        indent=2,
    )
    local_json = json.dumps(tracking_summary.local_storage, indent=2)
    session_json = json.dumps(tracking_summary.session_storage, indent=2)

    sections = [
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
        sections.extend([
            "",
            "## Pre-Consent Activity (before user granted consent)",
            f"- Cookies (before consent): {pre_consent_stats.total_cookies}"
            f" ({pre_consent_stats.tracking_cookies} tracking)",
            f"- Scripts (before consent): {pre_consent_stats.total_scripts}"
            f" ({pre_consent_stats.tracking_scripts} tracking)",
            f"- Requests (before consent): {pre_consent_stats.total_requests}"
            f" ({pre_consent_stats.tracker_requests} tracking)",
        ])

    sections.extend([
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
    ])

    if consent_details and (
        consent_details.categories or consent_details.partners
        or consent_details.claimed_partner_count
    ):
        cats = "\n".join(
            f"- {c.name} ({'Required' if c.required else 'Optional'}): {c.description}"
            for c in consent_details.categories
        ) or "None disclosed"

        partners = "\n".join(
            f"- {p.name}: {p.purpose}"
            for p in consent_details.partners[:50]
        ) or "None listed"

        claimed_count = consent_details.claimed_partner_count
        claimed_line = (
            f"\n### Claimed Partner Count: {claimed_count}"
            if claimed_count
            else ""
        )

        sections.extend([
            "",
            "## Consent Dialog Information",
            f"### Categories Disclosed ({len(consent_details.categories)})",
            cats,
            f"### Partners Listed ({len(consent_details.partners)})",
            partners,
            claimed_line,
            "### Stated Purposes",
            "\n".join(f"- {p}" for p in consent_details.purposes) or "None",
        ])

    if score_breakdown:
        risk_label = _risk_label(score_breakdown.total_score)
        top = ", ".join(score_breakdown.factors[:5]) or "none"
        cat_lines = "\n".join(
            f"- {name}: {cat.points}/{cat.max_points}"
            for name, cat in score_breakdown.categories.items()
            if cat.points > 0
        )
        sections.extend([
            "",
            "## Deterministic Privacy Score",
            f"Score: {score_breakdown.total_score}/100 ({risk_label})",
            f"Top factors: {top}",
            "",
            "Category breakdown:",
            cat_lines,
            "",
            "Your risk assessments MUST be consistent with this score.",
        ])

    return "\n".join(sections)
