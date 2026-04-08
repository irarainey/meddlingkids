"""Structured report agent for deterministic privacy reports.

Makes focused LLM calls for each report section, producing
structured JSON output rather than free-form markdown.  Each
section gets its own system prompt and response schema to
ensure consistent, professional output.

Section generation is orchestrated by a MAF ``Workflow``
(see :mod:`report_workflow`) using fan-out / fan-in for
concurrent execution.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib import parse

import pydantic

from src.agents import base, middleware, report_workflow
from src.analysis import domain_cache, domain_classifier
from src.data import loader
from src.models import analysis, consent, report
from src.utils import json_parsing, logger

log = logger.create_logger("StructuredReportAgent")


# ── Agent name ──────────────────────────────────────────────────

AGENT_NAME = "StructuredReportAgent"

# Severity sort order — critical first, least severe last.
_SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "very-high": 1,
    "high": 2,
    "medium": 3,
    "low": 4,
    "none": 5,
}


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


class _ConsentDigestResponse(pydantic.BaseModel):
    plain_language_summary: str


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
    max_tokens = 4096
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

        All 10 sections run concurrently via a MAF
        ``Workflow`` with fan-out / fan-in edges.

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

        # ── Deterministic tracking classification ───────────
        det_tracking, _unclassified = domain_classifier.build_deterministic_tracking_section(
            tracking_summary,
        )

        # ── Run all 10 sections via workflow ────────────────
        report_input = report_workflow.ReportInput(
            tracking_summary=tracking_summary,
            consent_details=consent_details,
            pre_consent_stats=pre_consent_stats,
            score_breakdown=score_breakdown,
            domain_knowledge=domain_knowledge,
        )

        log.info("Building all report sections concurrently via workflow...")
        section_map = await report_workflow.run_report_workflow(
            agent=self,
            report_input=report_input,
            consent_details=consent_details,
            social_media_trackers=det_tracking.social_media,
            on_section_done=on_section_done,
        )

        # ── Extract typed sections from workflow results ────
        tracking_tech = section_map.get("tracking-technologies")
        data_collection = section_map.get("data-collection")
        third_party = section_map.get("third-party-services")
        cookie_analysis = section_map.get("cookie-analysis")
        storage_analysis = section_map.get("storage-analysis")
        privacy_risk = section_map.get("privacy-risk")
        consent_analysis = section_map.get("consent-analysis")
        consent_digest = section_map.get("consent-digest")
        social_media_implications = section_map.get("social-media-implications")
        recommendations = section_map.get("recommendations")

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

        # ── Plain-language consent digest ───────────────────
        if consent_digest and isinstance(consent_digest, _ConsentDigestResponse):
            consent_sec.plain_language_summary = consent_digest.plain_language_summary

        # ── Deterministic user-rights note ──────────────────
        consent_sec.user_rights_note = _build_user_rights_note(consent_details)

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

        tracking_tech_sec = domain_classifier.merge_tracking_sections(
            det_tracking,
            _extract(tracking_tech, report.TrackingTechnologiesSection),
        )
        tracking_tech_sec = _enrich_tracker_urls(
            tracking_tech_sec,
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
            recommendations=_extract(
                recommendations,
                report.RecommendationsSection,
            ),
        )

        # ── Deterministic severity sorting ──────────────────
        # Sort all ranked lists from most severe to least so
        # the UI always shows critical issues first, regardless
        # of the order the LLM returned them.
        result.privacy_risk.factors.sort(
            key=lambda f: _SEVERITY_ORDER.get(f.severity, 9),
        )
        result.cookie_analysis.groups.sort(
            key=lambda g: _SEVERITY_ORDER.get(g.concern_level, 9),
        )
        result.consent_analysis.discrepancies.sort(
            key=lambda d: _SEVERITY_ORDER.get(d.severity, 9),
        )
        result.social_media_implications.risks.sort(
            key=lambda r: _SEVERITY_ORDER.get(r.severity, 9),
        )
        result.data_collection.items.sort(
            key=lambda i: _SEVERITY_ORDER.get(i.risk, 9),
        )

        log.end_timer("structured-report", "Structured report complete")
        return result

    async def build_section(
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
                except (pydantic.ValidationError, ValueError):
                    # Try unwrapping nested "section" key
                    if isinstance(raw, dict) and "section" in raw:
                        return response_cls.model_validate({"section": raw["section"]})

            # Include LLM response metadata so finish_reason and
            # token counts are visible when parsing fails (e.g.
            # finish_reason=length means the context was too large).
            meta = middleware._describe_response(response)
            log.warn(
                "Section parse failed",
                {"section": section_name, "llm": meta, "responsePreview": (response.text or "")[:200]},
            )
            return None
        except Exception as err:
            log.error(
                "Section generation failed",
                {"section": section_name, "error": str(err)},
            )
            return None


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


def _build_user_rights_note(
    consent_details: consent.ConsentDetails | None,
) -> str:
    """Build a plain-language note about the user's privacy rights.

    Deterministic — no LLM.  The note is generated when TCF
    infrastructure is detected (TC String present) and/or a
    consent platform is identified.

    Returns an empty string when no consent framework is detected.
    """
    if not consent_details:
        return ""

    has_tcf = bool(consent_details.tc_string_data)
    platform = consent_details.consent_platform

    if not has_tcf and not platform:
        return ""

    parts: list[str] = []

    if has_tcf:
        parts.append(
            "This site uses the IAB Transparency & Consent Framework (TCF), "
            "which means you have the right to withdraw your consent at any time."
        )
    elif platform:
        parts.append(
            f"This site uses {platform} for consent management. Under GDPR, you have the right to withdraw your consent at any time."
        )

    # Add practical action tip.
    if platform:
        parts.append(f'Look for "{platform}" or "Cookie Settings" in the page footer to change your preferences.')
    else:
        parts.append('Look for "Privacy Settings" or "Cookie Settings" in the page footer to change your preferences.')

    # Add key rights from the GDPR reference data.
    gdpr = loader.get_gdpr_reference()
    rights = gdpr.get("gdpr", {}).get("data_subject_rights", [])
    if rights and isinstance(rights, list):
        # Pick the 3 most relevant rights for a general audience.
        relevant = [r for r in rights if any(kw in r.lower() for kw in ("erasure", "access", "object"))]
        if relevant:
            rights_text = ", ".join(relevant[:3])
            parts.append(f"Your key rights include: {rights_text}.")

    return " ".join(parts)


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
