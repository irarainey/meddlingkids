"""Local consent text parser — no LLM required.

Extracts cookie categories, purposes, and partner names from
the raw DOM text captured from consent dialogs using regex
and heuristic matching.  Designed as a complement to LLM
extraction: runs in parallel and fills gaps when the LLM
is unavailable (content filter, timeout, etc.).
"""

from __future__ import annotations

import re

from src.models import consent
from src.utils import logger

log = logger.create_logger("ConsentTextParser")


# ── Consent-context gate ────────────────────────────────────────

# The local parser should only activate when the text clearly
# originates from a consent dialog.  Without this gate, news
# articles / navigation text that happens to include words
# like "ads", "analytics", or "performance" would produce
# false-positive categories.
_CONSENT_CONTEXT_RE = re.compile(
    r"cookie\s*(?:consent|settings|polic|prefer|categor|banner)"
    r"|consent\s*(?:manage|dialog|banner|preference|choice)"
    r"|we\s+(?:and\s+our\s+\d+\s+partners?|use\s+cookies)"
    r"|this\s+(?:site|website)\s+uses?\s+cookies"
    r"|manage\s+(?:my\s+)?(?:cookie|consent|privacy)"
    r"|accept\s+(?:all\s+)?cookies"
    r"|reject\s+(?:all\s+)?cookies"
    r"|data\s+processing\s+purposes?"
    r"|legitimate\s+interest"
    r"|tcf|iab\s+(?:europe|framework)"
    r"|GDPR",
    re.IGNORECASE,
)


# ── Well-known cookie categories ────────────────────────────────

# Patterns require cookie-specific phrasing (e.g. "necessary
# cookies", "performance cookies", "targeting cookies") to
# avoid matching generic page text.
_CATEGORY_PATTERNS: list[tuple[re.Pattern[str], str, str, bool]] = [
    (
        re.compile(
            r"(?:strictly\s+)?necessary\s+cookies?"
            r"|essential\s+cookies?"
            r"|required\s+cookies?",
            re.IGNORECASE,
        ),
        "Strictly Necessary",
        "Essential cookies required for the website to function.",
        True,
    ),
    (
        re.compile(
            r"performance\s+cookies?",
            re.IGNORECASE,
        ),
        "Performance",
        "Cookies that measure site performance and usage.",
        False,
    ),
    (
        re.compile(
            r"functional(?:ity)?\s+cookies?",
            re.IGNORECASE,
        ),
        "Functional",
        "Cookies that enable enhanced functionality and personalisation.",
        False,
    ),
    (
        re.compile(
            r"(?:targeting|advertising)\s+cookies?"
            r"|ad\s+cookies?",
            re.IGNORECASE,
        ),
        "Targeting / Advertising",
        "Cookies used to deliver targeted advertisements.",
        False,
    ),
    (
        re.compile(
            r"analytics?\s+cookies?"
            r"|measurement\s+cookies?",
            re.IGNORECASE,
        ),
        "Analytics",
        "Cookies that help understand how visitors interact with the site.",
        False,
    ),
    (
        re.compile(
            r"social\s*media\s+cookies?",
            re.IGNORECASE,
        ),
        "Social Media",
        "Cookies set by social media services for sharing and tracking.",
        False,
    ),
    (
        re.compile(
            r"personali[sz]ation\s+cookies?"
            r"|preference\s+cookies?",
            re.IGNORECASE,
        ),
        "Personalisation",
        "Cookies that remember user preferences and settings.",
        False,
    ),
]


# ── IAB TCF standard purposes ──────────────────────────────────

_PURPOSE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"store\s+and/or\s+access\s+information\s+on\s+a\s+device", re.IGNORECASE),
    re.compile(r"use\s+limited\s+data\s+to\s+select\s+advertising", re.IGNORECASE),
    re.compile(r"create\s+profiles?\s+for\s+personali[sz]ed\s+advertising", re.IGNORECASE),
    re.compile(r"use\s+profiles?\s+to\s+select\s+personali[sz]ed\s+advertising", re.IGNORECASE),
    re.compile(r"create\s+profiles?\s+to\s+personali[sz]e\s+content", re.IGNORECASE),
    re.compile(r"use\s+profiles?\s+to\s+select\s+personali[sz]ed\s+content", re.IGNORECASE),
    re.compile(r"measure\s+advertising\s+performance", re.IGNORECASE),
    re.compile(r"measure\s+content\s+performance", re.IGNORECASE),
    re.compile(r"understand\s+audiences?\s+through\s+statistics", re.IGNORECASE),
    re.compile(r"develop\s+and\s+improve\s+(?:products?|services?)", re.IGNORECASE),
    re.compile(r"use\s+limited\s+data\s+to\s+select\s+content", re.IGNORECASE),
    re.compile(r"ensure\s+security.*?prevent.*?(?:fraud|spam)", re.IGNORECASE),
]

# ── Manage-options button indicators ───────────────────────────

_MANAGE_OPTIONS_RE = re.compile(
    r"manage\s+(?:my\s+)?(?:options|preferences|settings|choices|cookies)"
    r"|cookie\s+settings"
    r"|customise\s+(?:my\s+)?choices"
    r"|more\s+options",
    re.IGNORECASE,
)

# ── Partner extraction ──────────────────────────────────────────

# Lines that look like partner/vendor names in a list context.
# We look for text blocks preceded by partner/vendor headings.
_PARTNER_SECTION_RE = re.compile(
    r"(?:partner|vendor|third.party|compan(?:y|ies))\s*(?:list|details)?",
    re.IGNORECASE,
)

# Lines to exclude — common UI/boilerplate text.
_PARTNER_EXCLUDE_RE = re.compile(
    r"^\s*$"
    r"|^(?:accept|reject|close|save|manage|learn\s+more|privacy\s+policy|cookie\s+policy|---)"
    r"|(?:cookie|consent|privacy|we\s+(?:and|use)|your\s+(?:privacy|choices|data))",
    re.IGNORECASE,
)


def parse_consent_text(text: str) -> consent.ConsentDetails:
    """Parse raw consent dialog text into structured details.

    Only activates when the text contains clear consent-dialog
    indicators (e.g. "cookie consent", "we use cookies",
    "manage preferences").  Without those markers the text is
    likely from non-consent page elements and parsing would
    produce false positives.

    Args:
        text: Raw consent text extracted from the DOM.

    Returns:
        Populated ``ConsentDetails`` with locally-parsed data,
        or an empty result when no consent context is found.
    """
    # Gate: only parse when we're confident this is consent text.
    if not _CONSENT_CONTEXT_RE.search(text):
        log.info(
            "No consent context found in text — skipping local parse",
            {"textLength": len(text)},
        )
        return consent.ConsentDetails.empty(
            text[:5000],
            claimed_partner_count=_extract_partner_count(text),
        )

    categories = _extract_categories(text)
    purposes = _extract_purposes(text)
    partners = _extract_partners(text)
    has_manage = bool(_MANAGE_OPTIONS_RE.search(text))
    partner_count = _extract_partner_count(text)

    log.info(
        "Local text parse complete",
        {
            "categories": len(categories),
            "purposes": len(purposes),
            "partners": len(partners),
            "hasManageOptions": has_manage,
            "claimedPartnerCount": partner_count,
        },
    )

    return consent.ConsentDetails(
        has_manage_options=has_manage,
        categories=categories,
        partners=partners,
        purposes=purposes,
        raw_text=text[:5000],
        claimed_partner_count=partner_count,
    )


def _extract_categories(text: str) -> list[consent.ConsentCategory]:
    """Extract cookie categories from consent text."""
    found: list[consent.ConsentCategory] = []
    seen: set[str] = set()
    for pattern, name, description, required in _CATEGORY_PATTERNS:
        if pattern.search(text) and name not in seen:
            seen.add(name)
            found.append(
                consent.ConsentCategory(
                    name=name,
                    description=description,
                    required=required,
                )
            )
    return found


def _extract_purposes(text: str) -> list[str]:
    """Extract IAB TCF purposes from consent text."""
    found: list[str] = []
    for pattern in _PURPOSE_PATTERNS:
        match = pattern.search(text)
        if match:
            # Use the matched text as the purpose name.
            purpose = match.group(0).strip()
            # Capitalise first letter.
            purpose = purpose[0].upper() + purpose[1:]
            if purpose not in found:
                found.append(purpose)
    return found


def _extract_partners(text: str) -> list[consent.ConsentPartner]:
    """Extract partner names from partner-list sections.

    Looks for sections headed by partner/vendor keywords and
    extracts individual lines as partner names.  Only returns
    partners when a clear list is found.
    """
    partners: list[consent.ConsentPartner] = []
    seen: set[str] = set()

    # Split text into sections delimited by '---'.
    sections = text.split("---")
    for section in sections:
        if not _PARTNER_SECTION_RE.search(section):
            continue

        # Look for PARTNER LIST blocks.
        if "PARTNER LIST:" in section:
            list_text = section.split("PARTNER LIST:", 1)[1]
            for line in list_text.strip().splitlines():
                name = line.strip().rstrip(",;.")
                if name and len(name) > 2 and len(name) < 100 and not _PARTNER_EXCLUDE_RE.search(name) and name not in seen:
                    seen.add(name)
                    partners.append(
                        consent.ConsentPartner(
                            name=name,
                            purpose="",
                            data_collected=[],
                        )
                    )

    return partners


# ── Partner count (shared with consent_extraction_agent) ────────

_PARTNER_COUNT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:we\s+and\s+)?our\s+(\d[\d,.]*)\s*\+?\s*partners?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(\d[\d,.]*)\s*\+?\s*(?:advertising|ad|iab|tcf)?\s*partners?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(\d[\d,.]*)\s*\+?\s*vendors?",
        re.IGNORECASE,
    ),
    re.compile(
        r"shar(?:e|ing)\s+(?:data\s+)?with\s+(\d[\d,.]*)\s*\+?\s*(?:partners?|vendors?|companies|third[ -]?parties)",
        re.IGNORECASE,
    ),
]


def _extract_partner_count(text: str) -> int | None:
    """Extract a claimed partner/vendor count from raw consent text."""
    counts: list[int] = []
    for pattern in _PARTNER_COUNT_PATTERNS:
        for match in pattern.finditer(text):
            try:
                raw_num = match.group(1).replace(",", "").replace(".", "")
                num = int(raw_num)
                if num >= 5:
                    counts.append(num)
            except (ValueError, IndexError):
                continue
    return max(counts) if counts else None
