"""Shared GDPR/TCF context builder for agent prompts.

Provides a single function that assembles a compact reference
section from the TCF, consent-cookie, and GDPR data files.
Both the ``TrackingAnalysisAgent`` and ``StructuredReportAgent``
use this to inject regulatory context into their LLM prompts.
"""

from __future__ import annotations

from src.data import loader


def build_gdpr_reference(*, heading: str = "## GDPR / TCF Reference") -> str:
    """Build a GDPR/TCF reference section for LLM prompts.

    Extracts key facts from the GDPR/TCF reference data files
    and formats them as a compact reference the LLM can use for
    accurate cookie classification, consent evaluation, and
    regulatory context.

    Args:
        heading: Markdown heading to use for the section.

    Returns:
        Formatted reference section string.
    """
    lines: list[str] = [heading]

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
