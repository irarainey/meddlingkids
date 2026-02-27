"""Structured report agent for deterministic privacy reports.

Makes focused LLM calls for each report section, producing
structured JSON output rather than free-form markdown. Each
section gets its own system prompt and response schema to
ensure consistent, professional output.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from urllib import parse

import pydantic

from src.agents import base, gdpr_context
from src.agents.prompts import structured_report
from src.analysis import domain_cache
from src.data import loader
from src.models import analysis, consent, report
from src.utils import json_parsing, logger, risk

log = logger.create_logger("StructuredReportAgent")


# ── Agent name ──────────────────────────────────────────────────

AGENT_NAME = "StructuredReportAgent"


# ── Per-section response wrappers ───────────────────────────────
# Each wrapper is a simple Pydantic model that the LLM fills
# via ``response_format``.  The agent swaps the wrapper for
# each section call.


class _TrackingTechResponse(pydantic.BaseModel):
    section: report.TrackingTechnologiesSection


class _DataCollectionResponse(pydantic.BaseModel):
    section: report.DataCollectionSection


class _ThirdPartyResponse(pydantic.BaseModel):
    section: report.ThirdPartySection


class _PrivacyRiskResponse(pydantic.BaseModel):
    section: report.PrivacyRiskSection


class _CookieAnalysisResponse(pydantic.BaseModel):
    section: report.CookieAnalysisSection


class _StorageAnalysisResponse(pydantic.BaseModel):
    section: report.StorageAnalysisSection


class _ConsentAnalysisResponse(pydantic.BaseModel):
    section: report.ConsentAnalysisSection


class _VendorResponse(pydantic.BaseModel):
    section: report.VendorSection


class _SocialMediaImplicationsResponse(pydantic.BaseModel):
    section: report.SocialMediaImplicationsSection


class _RecommendationsResponse(pydantic.BaseModel):
    section: report.RecommendationsSection


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
    call_timeout = 60  # Large prompts (100K+ chars) need more time than default
    response_model = None  # Set dynamically per section

    async def build_report(
        self,
        tracking_summary: analysis.TrackingSummary,
        consent_details: consent.ConsentDetails | None = None,
        pre_consent_stats: analysis.PreConsentStats | None = None,
        score_breakdown: analysis.ScoreBreakdown | None = None,
        domain_knowledge: domain_cache.DomainKnowledge | None = None,
        on_section_done: Callable[[str, int, int], None] | None = None,
    ) -> report.StructuredReport:
        """Build a complete structured report.

        All 10 sections run concurrently in a single batch —
        they are independent and share the same data context.

        Args:
            tracking_summary: Collected tracking data summary.
            consent_details: Optional consent dialog info.
            pre_consent_stats: Optional pre-consent statistics.
            score_breakdown: Deterministic privacy score, if
                available, so the LLM can calibrate risk levels.
            domain_knowledge: Optional cached classifications
                from a prior analysis of the same domain.
            on_section_done: Optional callback invoked as each
                section completes — ``(section_name, done, total)``.

        Returns:
            Complete ``StructuredReport``.
        """
        log.start_timer("structured-report")
        context = _build_data_context(
            tracking_summary,
            consent_details,
            pre_consent_stats,
            score_breakdown,
            domain_knowledge,
        )

        # All sections are independent — they share the same
        # data context and none reference another's output.
        # Running them in a single concurrent batch maximises
        # throughput.
        #
        # Wrap each coroutine so the optional progress callback
        # fires as sections finish, giving the client granular
        # "Building report: <section> (N/10)..." updates.
        _sections_done = 0
        _total_sections = 10

        async def _tracked(
            coro: Awaitable[pydantic.BaseModel | None],
            section_name: str,
        ) -> pydantic.BaseModel | None:
            nonlocal _sections_done
            result = await coro
            _sections_done += 1
            if on_section_done:
                on_section_done(section_name, _sections_done, _total_sections)
            return result

        consent_section_coro = (
            self._build_section(
                structured_report.CONSENT_ANALYSIS,
                context,
                _ConsentAnalysisResponse,
                "consent-analysis",
            )
            if consent_details and (consent_details.categories or consent_details.partners or consent_details.claimed_partner_count)
            else _noop_section(report.ConsentAnalysisSection())
        )

        log.info("Building all report sections concurrently...")
        (
            tracking_tech,
            data_collection,
            third_party,
            cookie_analysis,
            storage_analysis,
            privacy_risk,
            vendors,
            consent_analysis,
            social_media_implications,
            recommendations,
        ) = await asyncio.gather(
            _tracked(
                self._build_section(
                    structured_report.TRACKING_TECH,
                    context,
                    _TrackingTechResponse,
                    "tracking-technologies",
                ),
                "tracking-technologies",
            ),
            _tracked(
                self._build_section(
                    structured_report.DATA_COLLECTION,
                    context,
                    _DataCollectionResponse,
                    "data-collection",
                ),
                "data-collection",
            ),
            _tracked(
                self._build_section(
                    structured_report.THIRD_PARTY,
                    context,
                    _ThirdPartyResponse,
                    "third-party-services",
                ),
                "third-party-services",
            ),
            _tracked(
                self._build_section(
                    structured_report.COOKIE_ANALYSIS,
                    context,
                    _CookieAnalysisResponse,
                    "cookie-analysis",
                ),
                "cookie-analysis",
            ),
            _tracked(
                self._build_section(
                    structured_report.STORAGE_ANALYSIS,
                    context,
                    _StorageAnalysisResponse,
                    "storage-analysis",
                ),
                "storage-analysis",
            ),
            _tracked(
                self._build_section(
                    structured_report.PRIVACY_RISK,
                    context,
                    _PrivacyRiskResponse,
                    "privacy-risk",
                ),
                "privacy-risk",
            ),
            _tracked(
                self._build_section(
                    structured_report.VENDOR,
                    context,
                    _VendorResponse,
                    "key-vendors",
                ),
                "key-vendors",
            ),
            _tracked(
                consent_section_coro,
                "consent-analysis",
            ),
            _tracked(
                self._build_section(
                    structured_report.SOCIAL_MEDIA_IMPLICATIONS,
                    context,
                    _SocialMediaImplicationsResponse,
                    "social-media-implications",
                ),
                "social-media-implications",
            ),
            _tracked(
                self._build_section(
                    structured_report.RECOMMENDATIONS,
                    context,
                    _RecommendationsResponse,
                    "recommendations",
                ),
                "recommendations",
            ),
        )

        # ── Deterministic consent overrides ─────────────────
        # The LLM may miscount or omit consent dialog facts
        # that we already know deterministically.  Override
        # the relevant fields so the report is accurate.
        consent_sec = _extract(
            consent_analysis,
            report.ConsentAnalysisSection,
        )
        # Always clear LLM-provided CMP fields — they are set
        # deterministically below and the LLM may hallucinate
        # incorrect URLs (e.g. using a publisher's privacy
        # policy URL instead of the CMP's base URL).
        consent_sec.consent_platform = None
        consent_sec.consent_platform_url = None
        if consent_details:
            consent_sec.has_consent_dialog = True
            # Use the deterministic category count.
            if consent_details.categories:
                consent_sec.categories_disclosed = len(consent_details.categories)
            # Use the claimed partner count from the dialog
            # text (regex-extracted), falling back to the
            # number of individually extracted partners.
            if consent_details.claimed_partner_count:
                consent_sec.partners_disclosed = consent_details.claimed_partner_count
            elif consent_details.partners:
                consent_sec.partners_disclosed = len(consent_details.partners)
            if consent_details.consent_platform:
                consent_sec.consent_platform = consent_details.consent_platform
                # Look up the CMP's base URL from the partner database.
                cmp_db = loader.get_partner_database("consent-providers.json")
                cmp_lower = consent_details.consent_platform.lower().strip()
                for key, entry in cmp_db.items():
                    if key in cmp_lower or cmp_lower in key or any(a in cmp_lower for a in entry.aliases):
                        if entry.url:
                            consent_sec.consent_platform_url = entry.url
                        break

        # ── Deterministic third-party domain count ─────────
        # The LLM inconsistently counts whether to include
        # first-party subdomains.  Override with the
        # pre-computed third-party domain list length.
        third_party_sec = _extract(
            third_party,
            report.ThirdPartySection,
        )
        third_party_sec.total_domains = len(
            tracking_summary.third_party_domains,
        )

        # ── Deterministic cookie count ──────────────────────
        cookie_sec = _extract(
            cookie_analysis,
            report.CookieAnalysisSection,
        )
        cookie_sec.total = tracking_summary.total_cookies

        # ── Deterministic storage counts ────────────────────
        storage_sec = _extract(
            storage_analysis,
            report.StorageAnalysisSection,
        )
        storage_sec.local_storage_count = tracking_summary.local_storage_items
        storage_sec.session_storage_count = tracking_summary.session_storage_items

        # ── URL enrichment ──────────────────────────────────
        # Build a single name→URL lookup from all partner
        # databases and consent partners, then apply it to
        # every section that mentions company names.
        url_lookup = _build_url_lookup(consent_details)

        tracking_tech_sec = _enrich_tracker_urls(
            _extract(tracking_tech, report.TrackingTechnologiesSection),
            url_lookup,
        )
        data_collection_sec = _enrich_data_collection_urls(
            _extract(data_collection, report.DataCollectionSection),
            url_lookup,
        )
        third_party_sec = _enrich_third_party_urls(
            third_party_sec,
            url_lookup,
        )

        result = report.StructuredReport(
            tracking_technologies=tracking_tech_sec,
            data_collection=data_collection_sec,
            third_party_services=third_party_sec,
            privacy_risk=_extract(
                privacy_risk,
                report.PrivacyRiskSection,
            ),
            cookie_analysis=cookie_sec,
            storage_analysis=storage_sec,
            consent_analysis=consent_sec,
            social_media_implications=_extract(
                social_media_implications,
                report.SocialMediaImplicationsSection,
            ),
            key_vendors=_enrich_vendor_urls(
                _extract(
                    vendors,
                    report.VendorSection,
                ),
                url_lookup,
            ),
            recommendations=_extract(
                recommendations,
                report.RecommendationsSection,
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
                        return response_cls.model_validate({"section": raw["section"]})

            log.warn("Section parse failed", {"section": section_name})
            return None
        except Exception as err:
            log.error(
                "Section generation failed",
                {"section": section_name, "error": str(err)},
            )
            return None


async def _noop_section(
    default: pydantic.BaseModel,
) -> pydantic.BaseModel:
    """Return a default section without an LLM call."""
    return default


def _extract[S: pydantic.BaseModel](
    result: pydantic.BaseModel | None,
    section_cls: type[S],
) -> S:
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
        return section  # type: ignore[no-any-return]
    # If somehow the result itself is the section type
    if isinstance(result, section_cls):
        return result
    return section_cls()


# Path substrings that indicate a privacy/policy page
# rather than a company's base URL.
_PRIVACY_PATH_KEYWORDS = (
    "/privacy",
    "-privacy",
    "/policy",
    "-policy",
    "/legal",
    "/gdpr",
    "/data-protection",
    "/site-services",
    "/terms-of-service",
    "/terms-and-conditions",
)


def _is_base_url(url: str) -> bool:
    """Return ``True`` if the URL looks like a company base URL.

    Rejects URLs whose path contains privacy/policy keywords
    — these are informational pages, not the company's primary
    website.
    """

    path = parse.urlparse(url).path.lower()
    if not path or path == "/":
        return True
    return not any(kw in path for kw in _PRIVACY_PATH_KEYWORDS)


def _build_url_lookup(
    consent_details: consent.ConsentDetails | None = None,
) -> dict[str, str]:
    """Build a combined name→URL lookup from all partner databases and consent partners.

    The lookup maps lowercase company names (and aliases) to
    their canonical URLs.  Partner databases are checked first;
    consent partner URLs serve as a fallback.

    Args:
        consent_details: Optional consent details with enriched
            partner URLs from classification.

    Returns:
        Dict mapping lowercase name → URL.
    """
    urls: dict[str, str] = {}

    # Partner databases (authoritative).
    for config in loader.PARTNER_CATEGORIES:
        database = loader.get_partner_database(config.file)
        for key, entry in database.items():
            if entry.url and _is_base_url(entry.url) and key not in urls:
                urls[key] = entry.url
                for alias in entry.aliases:
                    alias_lower = alias.lower().strip()
                    if alias_lower not in urls:
                        urls[alias_lower] = entry.url

    # Consent partners (fallback).
    if consent_details:
        for partner in consent_details.partners:
            if partner.url and _is_base_url(partner.url):
                name_lower = partner.name.lower().strip()
                if name_lower not in urls:
                    urls[name_lower] = partner.url

    return urls


def _find_url(name: str, url_lookup: dict[str, str]) -> str:
    """Find the URL for a company name using fuzzy substring matching.

    Args:
        name: Company name to look up.
        url_lookup: Pre-built name→URL mapping.

    Returns:
        URL string, or empty string if not found.
    """
    name_lower = name.lower().strip()

    # Exact match.
    if name_lower in url_lookup:
        return url_lookup[name_lower]

    # Substring match (either direction).
    for key, url in url_lookup.items():
        if key in name_lower or name_lower in key:
            return url

    return ""


def _enrich_vendor_urls(
    vendor_section: report.VendorSection,
    url_lookup: dict[str, str],
) -> report.VendorSection:
    """Populate vendor URLs from the shared lookup.

    Authoritative URLs from the partner database always take
    precedence over LLM-provided URLs (which may be
    hallucinated or use privacy-policy pages instead of base
    URLs).

    Args:
        vendor_section: Vendor section from LLM output.
        url_lookup: Pre-built name→URL mapping.

    Returns:
        Updated vendor section with URLs populated where found.
    """
    for vendor in vendor_section.vendors:
        authoritative_url = _find_url(vendor.name, url_lookup)
        if authoritative_url:
            vendor.url = authoritative_url
    return vendor_section


def _enrich_tracker_urls(
    tracking_section: report.TrackingTechnologiesSection,
    url_lookup: dict[str, str],
) -> report.TrackingTechnologiesSection:
    """Populate tracker URLs from the shared lookup.

    Args:
        tracking_section: Tracking technologies section.
        url_lookup: Pre-built name→URL mapping.

    Returns:
        Updated section with URLs populated where found.
    """
    for category in (
        tracking_section.analytics,
        tracking_section.advertising,
        tracking_section.identity_resolution,
        tracking_section.social_media,
        tracking_section.other,
    ):
        for tracker in category:
            authoritative_url = _find_url(tracker.name, url_lookup)
            if authoritative_url:
                tracker.url = authoritative_url
    return tracking_section


def _enrich_named_entities(
    entities: list[report.NamedEntity],
    url_lookup: dict[str, str],
) -> None:
    """Populate URLs on a list of NamedEntity objects in place.

    Args:
        entities: List of named entities to enrich.
        url_lookup: Pre-built name→URL mapping.
    """
    for entity in entities:
        authoritative_url = _find_url(entity.name, url_lookup)
        if authoritative_url:
            entity.url = authoritative_url


def _enrich_data_collection_urls(
    data_section: report.DataCollectionSection,
    url_lookup: dict[str, str],
) -> report.DataCollectionSection:
    """Populate shared_with URLs in data collection items.

    Args:
        data_section: Data collection section.
        url_lookup: Pre-built name→URL mapping.

    Returns:
        Updated section with URLs populated where found.
    """
    for item in data_section.items:
        _enrich_named_entities(item.shared_with, url_lookup)
    return data_section


def _enrich_third_party_urls(
    third_party_section: report.ThirdPartySection,
    url_lookup: dict[str, str],
) -> report.ThirdPartySection:
    """Populate service URLs in third-party groups.

    Args:
        third_party_section: Third-party services section.
        url_lookup: Pre-built name→URL mapping.

    Returns:
        Updated section with URLs populated where found.
    """
    for group in third_party_section.groups:
        _enrich_named_entities(group.services, url_lookup)
    return third_party_section


def _build_data_context(
    tracking_summary: analysis.TrackingSummary,
    consent_details: consent.ConsentDetails | None = None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
    score_breakdown: analysis.ScoreBreakdown | None = None,
    domain_knowledge: domain_cache.DomainKnowledge | None = None,
) -> str:
    """Build the data context string sent to each section LLM call.

    Args:
        tracking_summary: Collected tracking data summary.
        consent_details: Optional consent dialog info.
        pre_consent_stats: Optional pre-consent statistics.
        score_breakdown: Deterministic privacy score, if
            available.
        domain_knowledge: Optional prior-run classifications
            for consistency anchoring.

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
        sections.extend(
            [
                "",
                "## Activity on Initial Page Load (before any dialogs were dismissed)",
                "NOTE: This is what was present when the page first loaded.",
                "We cannot confirm whether these scripts use the cookies listed,",
                "whether any dialog is a consent dialog, or whether this activity",
                "falls within the scope of what the user is asked to consent to.",
                f"- Cookies on load: {pre_consent_stats.total_cookies} ({pre_consent_stats.tracking_cookies} matched tracking patterns)",
                f"- Scripts on load: {pre_consent_stats.total_scripts} ({pre_consent_stats.tracking_scripts} matched tracking patterns)",
                f"- Requests on load: {pre_consent_stats.total_requests} ({pre_consent_stats.tracker_requests} matched tracking patterns)",
            ]
        )

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
        cats = (
            "\n".join(f"- {c.name} ({'Required' if c.required else 'Optional'}): {c.description}" for c in consent_details.categories)
            or "None disclosed"
        )

        partners = (
            "\n".join(f"- {p.name}: {p.purpose}" + (f" (URL: {p.url})" if p.url else "") for p in consent_details.partners[:50])
            or "None listed"
        )

        claimed_count = consent_details.claimed_partner_count
        claimed_line = f"\n### Claimed Partner Count: {claimed_count}" if claimed_count else ""

        sections.extend(
            [
                "",
                "## Consent Dialog Information",
                f"### Categories Disclosed ({len(consent_details.categories)})",
                cats,
                f"### Partners Listed ({len(consent_details.partners)})",
                partners,
                claimed_line,
                "### Stated Purposes",
                "\n".join(f"- {p}" for p in consent_details.purposes) or "None",
            ]
        )

    if score_breakdown:
        risk_label = risk.risk_label(score_breakdown.total_score)
        top = ", ".join(score_breakdown.factors[:5]) or "none"
        cat_lines = "\n".join(
            f"- {name}: {cat.points}/{cat.max_points}" for name, cat in score_breakdown.categories.items() if cat.points > 0
        )
        sections.extend(
            [
                "",
                "## Deterministic Privacy Score",
                f"Score: {score_breakdown.total_score}/100 ({risk_label})",
                f"Top factors: {top}",
                "",
                "Category breakdown:",
                cat_lines,
                "",
                "Your risk assessments MUST be consistent with this score.",
            ]
        )

    # Append prior-run classifications for consistency.
    if domain_knowledge:
        sections.append(domain_cache.build_context_hint(domain_knowledge))

    # Append GDPR/TCF reference data for informed analysis.
    sections.append(_build_gdpr_context())

    # Append known tracking cookie reference data.
    cookie_ctx = loader.build_tracking_cookie_context()
    if cookie_ctx:
        sections.append(cookie_ctx)

    # Append Disconnect tracker classifications for observed domains.
    disconnect_ctx = loader.build_disconnect_context(
        tracking_summary.third_party_domains,
    )
    if disconnect_ctx:
        sections.append(disconnect_ctx)

    # Append media group context when the domain is recognised.
    media_ctx = loader.build_media_group_context(tracking_summary.analyzed_url)
    if media_ctx:
        sections.append(media_ctx)

    return "\n".join(sections)


def _build_gdpr_context() -> str:
    """Build a concise GDPR/TCF reference section for LLM context.

    Delegates to the shared ``gdpr_context`` module so both
    this agent and the tracking-analysis agent use identical
    reference data.

    Returns:
        Formatted reference section string.
    """

    return "\n" + gdpr_context.build_gdpr_reference(
        heading="## GDPR / TCF Reference Data",
    )
