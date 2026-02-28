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
    r"|agree\s+to\s+cookies"
    r"|data\s+processing\s+purposes?"
    r"|legitimate\s+interest"
    r"|tcf|iab\s+(?:europe|framework)"
    r"|GDPR"
    # CMP-specific indicators
    r"|quantcast\s+choice"
    r"|inmobi\s+(?:choice|cmp)"
    r"|sourcepoint"
    r"|onetrust"
    r"|cookiebot"
    r"|didomi"
    r"|funding\s+choices"
    r"|privacy\s+(?:manager|center|centre|notice|wall)"
    # IAB TCF purpose phrases (standard wording)
    r"|store\s+and/or\s+access\s+information"
    r"|select\s+(?:basic|personali[sz]ed)\s+(?:ads?|advertising|content)"
    r"|create\s+(?:a\s+)?personali[sz]ed\s+(?:ads?|content)\s+profile"
    r"|measure\s+(?:ad|advertising|content)\s+performance"
    r"|understand\s+audiences?"
    r"|develop\s+and\s+improve\s+(?:products?|services?)"
    r"|use\s+limited\s+data\s+to\s+select"
    # Vendor / partner list indicators
    r"|(?:our\s+)?\d+\s*\+?\s*(?:partners?|vendors?)"
    r"|(?:partner|vendor)\s+list",
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
            r"|required\s+cookies?"
            # "Strictly Necessary" is specific enough standalone.
            r"|strictly\s+necessary",
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
            r"(?:targeting|advertising|marketing)\s+cookies?"
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
            r"|measurement\s+cookies?"
            r"|statistic(?:s|al)\s+cookies?",
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

# Each tuple is (pattern, canonical_name).  When a pattern
# matches, the *canonical_name* is used as the purpose string
# so that the output is normalised regardless of the wording
# variation found in the DOM text.
_PURPOSE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Purpose 1
    (
        re.compile(
            r"store\s+and/?or\s+access\s+information\s+on\s+a\s+device",
            re.IGNORECASE,
        ),
        "Store and/or access information on a device",
    ),
    # Purpose 2
    (
        re.compile(
            r"use\s+limited\s+data\s+to\s+select\s+(?:ads?|advertising)",
            re.IGNORECASE,
        ),
        "Use limited data to select advertising",
    ),
    # Purpose 3
    (
        re.compile(
            r"create\s+(?:a\s+)?profiles?\s+for\s+personali[sz]ed\s+(?:ads?|advertising)",
            re.IGNORECASE,
        ),
        "Create profiles for personalised advertising",
    ),
    # Purpose 4
    (
        re.compile(
            r"use\s+profiles?\s+to\s+select\s+personali[sz]ed\s+(?:ads?|advertising)",
            re.IGNORECASE,
        ),
        "Use profiles to select personalised advertising",
    ),
    # Purpose 5
    (
        re.compile(
            r"create\s+(?:a\s+)?profiles?\s+to\s+personali[sz]e\s+content",
            re.IGNORECASE,
        ),
        "Create profiles to personalise content",
    ),
    # Purpose 6
    (
        re.compile(
            r"use\s+profiles?\s+to\s+select\s+personali[sz]ed\s+content",
            re.IGNORECASE,
        ),
        "Use profiles to select personalised content",
    ),
    # Purpose 7
    (
        re.compile(
            r"measure\s+(?:ads?|advertising)\s+performance",
            re.IGNORECASE,
        ),
        "Measure advertising performance",
    ),
    # Purpose 8
    (
        re.compile(
            r"measure\s+content\s+performance",
            re.IGNORECASE,
        ),
        "Measure content performance",
    ),
    # Purpose 9
    (
        re.compile(
            r"understand\s+audiences?\s+(?:through|using|via)\s+statistics",
            re.IGNORECASE,
        ),
        "Understand audiences through statistics",
    ),
    # Purpose 10
    (
        re.compile(
            r"develop\s+and\s+improve\s+(?:products?|services?)",
            re.IGNORECASE,
        ),
        "Develop and improve services",
    ),
    # Purpose 11
    (
        re.compile(
            r"use\s+limited\s+data\s+to\s+select\s+content",
            re.IGNORECASE,
        ),
        "Use limited data to select content",
    ),
    # Special Purpose 1
    (
        re.compile(
            r"ensure\s+security.*?prevent.*?(?:fraud|spam)",
            re.IGNORECASE,
        ),
        "Ensure security, prevent and detect fraud, and fix errors",
    ),
    # Special Purpose 2
    (
        re.compile(
            r"technical(?:ly)?\s+deliver\s+(?:ads?|content)",
            re.IGNORECASE,
        ),
        "Technically deliver ads or content",
    ),
    # Special Feature 1
    (
        re.compile(
            r"(?:use\s+)?precise\s+geolocation\s+data",
            re.IGNORECASE,
        ),
        "Use precise geolocation data",
    ),
    # Special Feature 2
    (
        re.compile(
            r"actively\s+scan\s+device\s+characteristics",
            re.IGNORECASE,
        ),
        "Actively scan device characteristics for identification",
    ),
]

# Numbered purpose references (e.g. "Purpose 1", "Purpose 2:").
_PURPOSE_NUMBER_MAP: dict[int, str] = {
    1: "Store and/or access information on a device",
    2: "Use limited data to select advertising",
    3: "Create profiles for personalised advertising",
    4: "Use profiles to select personalised advertising",
    5: "Create profiles to personalise content",
    6: "Use profiles to select personalised content",
    7: "Measure advertising performance",
    8: "Measure content performance",
    9: "Understand audiences through statistics",
    10: "Develop and improve services",
    11: "Use limited data to select content",
}

_PURPOSE_NUMBER_RE = re.compile(
    r"purpose\s+(\d{1,2})\b",
    re.IGNORECASE,
)

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
    platform = _detect_consent_platform(text)

    log.info(
        "Local text parse complete",
        {
            "categories": len(categories),
            "purposes": len(purposes),
            "partners": len(partners),
            "hasManageOptions": has_manage,
            "claimedPartnerCount": partner_count,
            "consentPlatform": platform,
        },
    )

    return consent.ConsentDetails(
        has_manage_options=has_manage,
        categories=categories,
        partners=partners,
        purposes=purposes,
        raw_text=text[:5000],
        claimed_partner_count=partner_count,
        consent_platform=platform,
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
    seen: set[str] = set()

    # Pattern-based extraction using canonical names.
    for pattern, canonical in _PURPOSE_PATTERNS:
        if pattern.search(text) and canonical.lower() not in seen:
            seen.add(canonical.lower())
            found.append(canonical)

    # Numbered purpose references (e.g. "Purpose 1", "Purpose 3:").
    for match in _PURPOSE_NUMBER_RE.finditer(text):
        try:
            num = int(match.group(1))
        except ValueError:
            continue
        canonical = _PURPOSE_NUMBER_MAP.get(num, "")
        if canonical and canonical.lower() not in seen:
            seen.add(canonical.lower())
            found.append(canonical)

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
                    if not consent.is_plausible_partner_name(name):
                        continue
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


# ── Consent platform detection ──────────────────────────────────

# Ordered by specificity: most unique identifiers first.
_PLATFORM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\binmobi\s*(?:choice|cmp)\b", re.IGNORECASE), "InMobi Choice"),
    (re.compile(r"\bquantcast\s*(?:choice)?\b", re.IGNORECASE), "InMobi Choice"),
    (re.compile(r"\bsourcepoint\b", re.IGNORECASE), "Sourcepoint"),
    (re.compile(r"\bonetrust\b|optanon", re.IGNORECASE), "OneTrust"),
    (re.compile(r"\bcookiebot\b|\bcybot\b", re.IGNORECASE), "Cookiebot"),
    (re.compile(r"\bdidomi\b", re.IGNORECASE), "Didomi"),
    (re.compile(r"\btrust\s*arc\b|\btruste\b", re.IGNORECASE), "TrustArc"),
    (re.compile(r"\bfunding\s+choices?\b", re.IGNORECASE), "Google Funding Choices"),
    (re.compile(r"\busercentric[sz]?\b", re.IGNORECASE), "Usercentrics"),
    (re.compile(r"\bcivic\s*cookie\b", re.IGNORECASE), "Civic Cookie Control"),
    (re.compile(r"\bketch\b", re.IGNORECASE), "Ketch"),
]


def _detect_consent_platform(text: str) -> str | None:
    """Detect the consent management platform from DOM text.

    Returns the first matching platform name, or ``None``.
    """
    for pattern, name in _PLATFORM_PATTERNS:
        if pattern.search(text):
            return name
    return None
