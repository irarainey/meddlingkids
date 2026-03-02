"""Tracking analysis agent for privacy risk assessment.

Generates a structured JSON privacy analysis by examining
cookies, scripts, network requests, and storage data.
Consistent with other agents' structured-output approach.
"""

from __future__ import annotations

import json

from src.agents import base, config, gdpr_context
from src.agents.prompts import tracking_analysis
from src.analysis import domain_cache
from src.data import loader
from src.models import analysis, consent
from src.utils import json_parsing, logger, risk

log = logger.create_logger("TrackingAnalysisAgent")


# ── Private response wrapper ───────────────────────────────────
# The LLM sees this schema via ``response_format``.  We map
# the parsed result to the public ``TrackingAnalysisResult``
# model in ``models.analysis`` before returning.

import pydantic  # noqa: E402 (grouped after local imports)


class _TrackingAnalysisResponse(pydantic.BaseModel):
    """Schema pushed to the LLM via ``response_format``."""

    risk_level: analysis.RiskLevel
    risk_summary: str
    sections: list[analysis.TrackingAnalysisSection]


# ── Agent class ─────────────────────────────────────────────────


class TrackingAnalysisAgent(base.BaseAgent):
    """Agent that generates structured privacy analysis reports.

    Uses ``response_format`` with a JSON schema to produce
    typed output, consistent with StructuredReportAgent and
    SummaryFindingsAgent.
    """

    agent_name = config.AGENT_TRACKING_ANALYSIS
    instructions = tracking_analysis.INSTRUCTIONS
    max_tokens = 4096
    max_retries = 5
    call_timeout = 60  # Large prompts need more time
    response_model = _TrackingAnalysisResponse

    async def analyze(
        self,
        tracking_summary: analysis.TrackingSummary,
        consent_details: consent.ConsentDetails | None = None,
        pre_consent_stats: analysis.PreConsentStats | None = None,
        score_breakdown: analysis.ScoreBreakdown | None = None,
        domain_knowledge: domain_cache.DomainKnowledge | None = None,
        *,
        decoded_cookies: dict[str, object] | None = None,
    ) -> analysis.TrackingAnalysisResult:
        """Run the tracking analysis and return structured output.

        Args:
            tracking_summary: Collected tracking data summary.
            consent_details: Optional consent dialog info.
            pre_consent_stats: Optional pre-consent page-load stats.
            score_breakdown: Deterministic privacy score so the
                LLM can calibrate its risk assessment.
            domain_knowledge: Prior-run classifications for
                consistency anchoring.

        Returns:
            Structured ``TrackingAnalysisResult``.

        Raises:
            TimeoutError: If the LLM call exceeds
                ``call_timeout`` on every retry.
        """
        prompt = _build_user_prompt(
            tracking_summary,
            consent_details,
            pre_consent_stats,
            score_breakdown,
            domain_knowledge,
            decoded_cookies=decoded_cookies,
        )
        log.info(
            "Starting tracking analysis",
            {
                "promptChars": len(prompt),
                "hasConsent": consent_details is not None,
            },
        )

        response = await self._complete(prompt)

        parsed = self._parse_response(response, _TrackingAnalysisResponse)
        if parsed:
            result = analysis.TrackingAnalysisResult(
                risk_level=parsed.risk_level,
                risk_summary=parsed.risk_summary,
                sections=parsed.sections,
            )
            log.info(
                "Tracking analysis complete",
                {
                    "riskLevel": result.risk_level,
                    "sections": len(result.sections),
                },
            )
            return result

        # Fallback: try manual JSON parse from text
        log.warn("Structured parse failed — attempting text fallback")
        fallback = _parse_text_fallback(response.text)
        if fallback:
            log.info(
                "Text fallback succeeded",
                {
                    "riskLevel": fallback.risk_level,
                    "sections": len(fallback.sections),
                },
            )
            return fallback

        # Last resort: wrap the raw text as a single section
        log.warn("All parsing failed — wrapping raw text")
        return analysis.TrackingAnalysisResult(
            risk_level="medium",
            risk_summary="Unable to parse structured analysis.",
            sections=[
                analysis.TrackingAnalysisSection(
                    heading="Raw Analysis",
                    content=response.text or "",
                ),
            ],
        )


# ── Text fallback parser ────────────────────────────────────────


def _parse_text_fallback(
    text: str | None,
) -> analysis.TrackingAnalysisResult | None:
    """Try to parse a ``TrackingAnalysisResult`` from raw text.

    The LLM sometimes wraps JSON in code fences even when
    structured output is requested.  This falls back to
    ``json_parsing.load_json_from_text`` and then
    validates the result.

    Args:
        text: Raw response text.

    Returns:
        Parsed result or ``None`` on failure.
    """
    data = json_parsing.load_json_from_text(text)
    if data is None:
        return None
    try:
        return analysis.TrackingAnalysisResult.model_validate(data)
    except Exception:
        return None


# ── Prompt builders ─────────────────────────────────────────────


def _build_user_prompt(
    tracking_summary: analysis.TrackingSummary,
    consent_details: consent.ConsentDetails | None = None,
    pre_consent_stats: analysis.PreConsentStats | None = None,
    score_breakdown: analysis.ScoreBreakdown | None = None,
    domain_knowledge: domain_cache.DomainKnowledge | None = None,
    *,
    decoded_cookies: dict[str, object] | None = None,
) -> str:
    """Build the user prompt from tracking data.

    Args:
        tracking_summary: Collected tracking data summary.
        consent_details: Optional consent dialog info.
        pre_consent_stats: Optional pre-consent page-load stats.
        score_breakdown: Deterministic privacy score.
        domain_knowledge: Prior-run domain classifications.

    Returns:
        Formatted user prompt string.
    """
    consent_section = ""
    if consent_details and (consent_details.categories or consent_details.partners or consent_details.claimed_partner_count):
        consent_section = _build_consent_section(consent_details)

    tc_ac_section = _build_tc_ac_section(consent_details)
    decoded_section = _build_decoded_cookies_section(decoded_cookies)

    breakdown = json.dumps(
        [d.model_dump() for d in tracking_summary.domain_breakdown],
        indent=2,
    )
    local_json = json.dumps(tracking_summary.local_storage, indent=2)
    session_json = json.dumps(tracking_summary.session_storage, indent=2)

    pre_consent_section = ""
    if pre_consent_stats:
        pre_consent_section = _build_pre_consent_section(pre_consent_stats)

    score_section = _build_score_section(score_breakdown)
    knowledge_section = _build_knowledge_section(domain_knowledge)

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
        f"{consent_section}"
        f"{tc_ac_section}"
        f"{decoded_section}\n\n"
        f"{score_section}"
        f"{knowledge_section}"
        f"{_build_gdpr_reference()}\n\n"
        f"{loader.build_tracking_cookie_context()}\n\n"
        f"{loader.build_disconnect_context(tracking_summary.third_party_domains)}\n\n"
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

    Delegates to the shared ``gdpr_context`` module so both
    this agent and the structured-report agent use identical
    reference data.

    Returns:
        Formatted reference section string.
    """

    return gdpr_context.build_gdpr_reference(heading="## GDPR / TCF Reference")


def _build_score_section(
    score_breakdown: analysis.ScoreBreakdown | None,
) -> str:
    """Build a deterministic-score context section.

    When a score breakdown is available, format it as a reference
    the LLM must stay consistent with.

    Args:
        score_breakdown: Pre-computed privacy score, or ``None``.

    Returns:
        Formatted section string (empty when *score_breakdown* is ``None``).
    """
    if not score_breakdown:
        return ""

    label = risk.risk_label(score_breakdown.total_score)
    top = ", ".join(score_breakdown.factors[:5]) or "none"
    cat_lines = "\n".join(
        f"  - {name}: {cat.points}/{cat.max_points}" for name, cat in score_breakdown.categories.items() if cat.points > 0
    )

    return (
        "## Deterministic Privacy Score\n"
        f"Total: {score_breakdown.total_score}/100 — **{label}**\n"
        f"Top factors: {top}\n"
        f"Category breakdown:\n{cat_lines}\n\n"
        "Your risk assessments MUST be consistent with this score.\n\n"
    )


def _build_knowledge_section(
    domain_knowledge: domain_cache.DomainKnowledge | None,
) -> str:
    """Build a domain-knowledge context section.

    Delegates to ``domain_cache.build_context_hint`` when knowledge
    is available.

    Args:
        domain_knowledge: Prior-run domain classifications, or ``None``.

    Returns:
        Formatted section string (empty when *domain_knowledge* is ``None``).
    """
    if not domain_knowledge:
        return ""

    return domain_cache.build_context_hint(domain_knowledge) + "\n\n"


def _build_tc_ac_section(
    consent_details: consent.ConsentDetails | None,
) -> str:
    """Build TC String, AC String, and TC Validation context.

    Provides the LLM with the actual encoded consent signals
    so it can compare what was disclosed in the dialog with
    what was actually recorded in the consent strings.

    Args:
        consent_details: Consent details (may contain tc_string_data,
            ac_string_data, and tc_validation).

    Returns:
        Formatted section string (empty when no consent signal
        data is available).
    """
    if not consent_details:
        return ""

    parts: list[str] = []

    tc = consent_details.tc_string_data
    if tc:
        purposes = tc.get("purposeConsents", [])
        li_purposes = tc.get("purposeLegitimateInterests", [])
        special = tc.get("specialFeatureOptIns", [])
        lines = [
            "\n\n## TC String (euconsent-v2) — Actual Consent Signals",
            f"- CMP ID: {tc.get('cmpId', '?')}",
            f"- CMP version: {tc.get('cmpVersion', '?')}",
            f"- Consent language: {tc.get('consentLanguage', '?')}",
            f"- Vendor list version: {tc.get('vendorListVersion', '?')}",
            f"- Publisher country: {tc.get('publisherCountryCode', '?')}",
            f"- Service-specific: {tc.get('isServiceSpecific', '?')}",
            f"- Created: {tc.get('created', '?')}",
            f"- Last updated: {tc.get('lastUpdated', '?')}",
        ]
        if purposes:
            lines.append(f"- Purpose consents: {purposes}")
        if li_purposes:
            lines.append(f"- Purpose legitimate interests: {li_purposes}")
        if special:
            lines.append(f"- Special feature opt-ins: {special}")
        lines.append(f"- Vendor consents: {tc.get('vendorConsentCount', 0)}")
        lines.append(f"- Vendor legitimate interests: {tc.get('vendorLiCount', 0)}")
        parts.append("\n".join(lines))

    ac = consent_details.ac_string_data
    if ac:
        resolved = list(ac.get("resolvedProviders", []))  # type: ignore[call-overload]
        lines = [
            "\n\n## AC String (addtl_consent) — Google Additional Consent",
            f"- Version: {ac.get('version', '?')}",
            f"- Vendor count: {ac.get('vendorCount', 0)}",
        ]
        if resolved:
            names = [p.get("name", str(p.get("id", "?"))) for p in resolved[:30]]  # type: ignore[union-attr]
            lines.append(f"- Resolved providers ({len(resolved)}): {', '.join(names)}")
            if len(resolved) > 30:
                lines.append(f"  ... and {len(resolved) - 30} more")
        unresolved = ac.get("unresolvedProviderCount", 0)
        if unresolved:
            lines.append(f"- Unresolved provider IDs: {unresolved}")
        parts.append("\n".join(lines))

    val = consent_details.tc_validation
    if val:
        findings: list[dict[str, object]] = val.get("findings", [])  # type: ignore[assignment]
        mismatch = val.get("vendorCountMismatch", False)
        if findings or mismatch:
            lines = [
                "\n\n## TC Validation — Consent Signal Discrepancies",
                f"- Vendor consents in TC String: {val.get('vendorConsentCount', 0)}",
                f"- Vendor LI in TC String: {val.get('vendorLiCount', 0)}",
            ]
            claimed = val.get("claimedPartnerCount")
            if claimed is not None:
                lines.append(f"- Claimed partner count (from dialog): {claimed}")
            if mismatch:
                lines.append("- WARNING: Vendor count mismatch between dialog and TC String")
            if findings:
                lines.append("- Findings:")
                for f in findings:
                    sev = str(f.get("severity", "?")).upper()
                    title = f.get("title", "")
                    detail = f.get("detail", "")
                    lines.append(f"  [{sev}] {title}")
                    if detail:
                        lines.append(f"    {detail}")
            parts.append("\n".join(lines))

    return "".join(parts)


def _build_decoded_cookies_section(
    decoded_cookies: dict[str, object] | None,
) -> str:
    """Build decoded privacy cookies context for the LLM prompt.

    Provides ground-truth consent state from decoded cookie
    values (OneTrust categories, USP string, GPP string,
    Google Analytics client ID, Facebook pixel data, etc.).

    Args:
        decoded_cookies: Decoded cookie data, or ``None``.

    Returns:
        Formatted section string (empty when no decoded
        cookies are available).
    """
    if not decoded_cookies:
        return ""

    lines = ["\n\n## Decoded Privacy Cookies — Ground-Truth Consent State"]

    usp = decoded_cookies.get("uspString")
    if isinstance(usp, dict):
        lines.append(f"- USP String: {usp.get('rawString', '?')}")
        lines.append(f"  Notice: {usp.get('noticeLabel', '?')}, Opt-out: {usp.get('optOutLabel', '?')}, LSPA: {usp.get('lspaLabel', '?')}")

    gpp = decoded_cookies.get("gppString")
    if isinstance(gpp, dict):
        sections = gpp.get("sections", [])
        section_names = [s.get("name", str(s.get("id"))) for s in sections] if isinstance(sections, list) else []  # type: ignore[union-attr]
        lines.append(f"- GPP String: segments={gpp.get('segmentCount', '?')}")
        if section_names:
            lines.append(f"  Sections: {', '.join(section_names)}")

    ga = decoded_cookies.get("googleAnalytics")
    if isinstance(ga, dict):
        lines.append(f"- Google Analytics (_ga): clientId={ga.get('clientId', '?')}, firstVisit={ga.get('firstVisit', '?')}")

    fb = decoded_cookies.get("facebookPixel")
    if isinstance(fb, dict):
        fbp = fb.get("fbp")
        fbc = fb.get("fbc")
        if isinstance(fbp, dict):
            lines.append(f"- Facebook _fbp: browserId={fbp.get('browserId', '?')}, created={fbp.get('created', '?')}")
        if isinstance(fbc, dict):
            lines.append(f"- Facebook _fbc: click tracking active, clicked={fbc.get('clicked', '?')}")

    gads = decoded_cookies.get("googleAds")
    if isinstance(gads, dict):
        gau = gads.get("gclAu")
        gaw = gads.get("gclAw")
        if isinstance(gau, dict):
            lines.append(f"- Google Ads _gcl_au: v{gau.get('version', '?')}, created={gau.get('created', '?')}")
        if isinstance(gaw, dict):
            lines.append(f"- Google Ads _gcl_aw: click tracking active, clicked={gaw.get('clicked', '?')}")

    ot = decoded_cookies.get("oneTrust")
    if isinstance(ot, dict):
        cats = ot.get("categories", [])
        if isinstance(cats, list):
            consented = [c.get("name", c.get("id", "?")) for c in cats if isinstance(c, dict) and c.get("consented")]
            declined = [c.get("name", c.get("id", "?")) for c in cats if isinstance(c, dict) and not c.get("consented")]
            lines.append(
                f"- OneTrust consent state: consented=[{', '.join(str(x) for x in consented)}], declined=[{', '.join(str(x) for x in declined)}]"
            )
        if ot.get("isGpcApplied"):
            lines.append("  GPC signal applied")

    cb = decoded_cookies.get("cookiebot")
    if isinstance(cb, dict):
        cats = cb.get("categories", [])
        if isinstance(cats, list):
            cb_consented = [str(c.get("name", "?")) for c in cats if isinstance(c, dict) and c.get("consented")]
            cb_declined = [str(c.get("name", "?")) for c in cats if isinstance(c, dict) and not c.get("consented")]
            lines.append(f"- Cookiebot consent state: consented=[{', '.join(cb_consented)}], declined=[{', '.join(cb_declined)}]")

    socs = decoded_cookies.get("googleSocs")
    if isinstance(socs, dict):
        lines.append(f"- Google SOCS: consentMode={socs.get('consentMode', '?')}")

    # Only return the section if we actually decoded something.
    if len(lines) <= 1:
        return ""

    return "\n".join(lines)
