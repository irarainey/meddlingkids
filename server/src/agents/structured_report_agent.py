"""Structured report agent for deterministic privacy reports.

Makes focused LLM calls for each report section, producing
structured JSON output rather than free-form markdown. Each
section gets its own system prompt and response schema to
ensure consistent, professional output.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from urllib import parse

import pydantic

from src.agents import base, context_builder, middleware
from src.agents.prompts import structured_report
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

        # ── Deterministic tracking classification ───────────
        # Classify domains from local databases (Disconnect,
        # partner DBs) before any LLM calls.  This provides
        # instant, deterministic results for known domains
        # and reduces LLM token usage.
        det_tracking, _unclassified = domain_classifier.build_deterministic_tracking_section(
            tracking_summary,
        )

        # Build per-section context strings — each section
        # receives only the data blocks it actually needs,
        # reducing token usage by 30–90 % compared to the
        # old shared-context approach.
        def _ctx(section_name: str) -> str:
            return context_builder.build_section_context(
                section_name,
                tracking_summary,
                consent_details=consent_details,
                pre_consent_stats=pre_consent_stats,
                score_breakdown=score_breakdown,
                domain_knowledge=domain_knowledge,
                social_media_trackers=det_tracking.social_media,
            )

        # All sections are independent — they share the same
        # data context and none reference another's output.
        # Running them in a single concurrent batch maximises
        # throughput.
        #
        # Wrap each coroutine so the optional progress callback
        # fires as sections finish, giving the client granular
        # "Generating report: <section> (N/10)..." updates.
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
                _ctx("consent-analysis"),
                _ConsentAnalysisResponse,
                "consent-analysis",
            )
            if consent_details and (consent_details.categories or consent_details.partners or consent_details.claimed_partner_count)
            else _noop_section(report.ConsentAnalysisSection())
        )

        consent_digest_coro = (
            self._build_section(
                structured_report.CONSENT_DIGEST,
                _ctx("consent-digest"),
                _ConsentDigestResponse,
                "consent-digest",
            )
            if consent_details and (consent_details.categories or consent_details.partners or consent_details.claimed_partner_count)
            else _noop_section(_ConsentDigestResponse(plain_language_summary=""))
        )

        log.info("Building all report sections concurrently...")
        (
            tracking_tech,
            data_collection,
            third_party,
            cookie_analysis,
            storage_analysis,
            privacy_risk,
            consent_analysis,
            consent_digest,
            social_media_implications,
            recommendations,
        ) = await asyncio.gather(
            _tracked(
                self._build_section(
                    structured_report.TRACKING_TECH,
                    _ctx("tracking-technologies"),
                    _TrackingTechResponse,
                    "tracking-technologies",
                ),
                "tracking-technologies",
            ),
            _tracked(
                self._build_section(
                    structured_report.DATA_COLLECTION,
                    _ctx("data-collection"),
                    _DataCollectionResponse,
                    "data-collection",
                ),
                "data-collection",
            ),
            _tracked(
                self._build_section(
                    structured_report.THIRD_PARTY,
                    _ctx("third-party-services"),
                    _ThirdPartyResponse,
                    "third-party-services",
                ),
                "third-party-services",
            ),
            _tracked(
                self._build_section(
                    structured_report.COOKIE_ANALYSIS,
                    _ctx("cookie-analysis"),
                    _CookieAnalysisResponse,
                    "cookie-analysis",
                ),
                "cookie-analysis",
            ),
            _tracked(
                self._build_section(
                    structured_report.STORAGE_ANALYSIS,
                    _ctx("storage-analysis"),
                    _StorageAnalysisResponse,
                    "storage-analysis",
                ),
                "storage-analysis",
            ),
            _tracked(
                self._build_section(
                    structured_report.PRIVACY_RISK,
                    _ctx("privacy-risk"),
                    _PrivacyRiskResponse,
                    "privacy-risk",
                ),
                "privacy-risk",
            ),
            _tracked(
                consent_section_coro,
                "consent-analysis",
            ),
            _tracked(
                consent_digest_coro,
                "consent-digest",
            ),
            _tracked(
                self._build_section(
                    structured_report.SOCIAL_MEDIA_IMPLICATIONS,
                    _ctx("social-media-implications"),
                    _SocialMediaImplicationsResponse,
                    "social-media-implications",
                ),
                "social-media-implications",
            ),
            _tracked(
                self._build_section(
                    structured_report.RECOMMENDATIONS,
                    _ctx("recommendations"),
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

        # ── Plain-language consent digest ───────────────────
        if consent_digest and isinstance(consent_digest, _ConsentDigestResponse):
            consent_sec.plain_language_summary = consent_digest.plain_language_summary

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
