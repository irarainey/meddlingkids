"""Consent extraction agent using LLM vision.

Extracts detailed consent dialog information — cookie
categories, third-party partners, data-collection purposes
— from screenshots and page text using a structured output
schema.
"""

from __future__ import annotations

import asyncio
import pathlib
import re

import pydantic
from playwright import async_api

from src.agents import base, config
from src.models import consent
from src.utils import errors, json_parsing, logger

log = logger.create_logger("ConsentExtractionAgent")

# Pre-load JavaScript snippets evaluated in the browser.
_SCRIPTS_DIR = pathlib.Path(__file__).parent / "scripts"
_EXTRACT_CONSENT_JS = (
    (_SCRIPTS_DIR / "extract_consent_text.js").read_text()
)
_EXTRACT_IFRAME_JS = (
    (_SCRIPTS_DIR / "extract_iframe_text.js").read_text()
)
# ── Structured output models ───────────────────────────────────

class _CategoryResponse(pydantic.BaseModel):
    """Cookie category from the consent dialog."""

    name: str
    description: str
    required: bool = False


class _PartnerResponse(pydantic.BaseModel):
    """Third-party partner/vendor from the consent dialog."""

    name: str
    purpose: str = ""
    dataCollected: list[str] = pydantic.Field(
        default_factory=list
    )


class _ConsentExtractionResponse(pydantic.BaseModel):
    """Schema pushed to the LLM via ``response_format``."""

    hasManageOptions: bool = False
    manageOptionsSelector: str | None = None
    categories: list[_CategoryResponse] = pydantic.Field(
        default_factory=list
    )
    partners: list[_PartnerResponse] = pydantic.Field(
        default_factory=list
    )
    purposes: list[str] = pydantic.Field(
        default_factory=list
    )
    claimedPartnerCount: int | None = None


# ── System prompt ───────────────────────────────────────────────

_INSTRUCTIONS = """\
You are an expert at analyzing cookie consent dialogs and \
extracting detailed information about tracking and data \
collection.

Your task is to extract ALL information about:
1. Cookie categories (necessary, functional, analytics, \
advertising, etc.)
2. Third-party partners/vendors and what they do — EXTRACT \
ALL PARTNERS, even if there are hundreds
3. What data is being collected
4. Purposes of data collection
5. Any retention periods mentioned

IMPORTANT INSTRUCTIONS FOR PARTNERS:
- Look for "View Partners", "Show Vendors", "IAB Vendors", \
or similar expandable sections
- Many consent dialogs hide the full partner list behind a \
button — look for this in the HTML
- TCF dialogs often have 100+ partners — include them ALL
- If you see text like "We and our 842 partners" or similar, \
there is a partner list somewhere
- Partner lists may be in tables, lists, or accordion sections
- Include EVERY partner name you can find

IMPORTANT: If the consent dialog text mentions a specific \
number of partners (e.g. "We and our 1467 partners", \
"842 vendors", "sharing data with 500+ partners"), \
extract that number into the claimedPartnerCount field. \
This is the number the dialog CLAIMS, regardless of how \
many individual partner names you can find.

Also identify if there is a "Manage Preferences", \
"Cookie Settings", "More Options", or similar button that \
reveals more details.

Return ONLY a JSON object matching the required schema."""


# ── Agent class ─────────────────────────────────────────────────

class ConsentExtractionAgent(base.BaseAgent):
    """Vision agent that extracts consent dialog details.

    Sends a screenshot + extracted page text to the LLM and
    returns typed ``ConsentDetails``.
    """

    agent_name = config.AGENT_CONSENT_EXTRACTION
    instructions = _INSTRUCTIONS
    max_tokens = 4096
    max_retries = 5
    response_model = _ConsentExtractionResponse

    async def extract(
        self,
        page: async_api.Page,
        screenshot: bytes,
        *,
        pre_captured_text: str | None = None,
    ) -> consent.ConsentDetails:
        """Extract consent details from a page screenshot.

        Args:
            page: Playwright page for DOM text extraction.
            screenshot: Raw PNG screenshot bytes.
            pre_captured_text: DOM text captured while the
                consent dialog was still visible.  When
                provided, skips live DOM extraction (the
                dialog may already be dismissed).

        Returns:
            Structured ``ConsentDetails``.
        """
        log.info("Extracting consent details from page...")

        log.start_timer("text-extraction")
        if pre_captured_text:
            consent_text = pre_captured_text
            log.info(
                "Using pre-captured consent text",
                {"length": len(consent_text)},
            )
        else:
            consent_text = await _extract_consent_text(page)
        log.end_timer(
            "text-extraction", "Text extraction complete"
        )
        log.debug(
            "Extracted consent text",
            {"length": len(consent_text)},
        )

        log.start_timer("vision-extraction")
        log.info("Analysing consent dialog with vision...")

        try:
            response = await asyncio.wait_for(
                self._complete_vision(
                    user_text=(
                        "Analyze this cookie consent dialog"
                        " screenshot and extracted text to"
                        " find ALL information about tracking,"
                        " partners, and data collection.\n\n"
                        "Extracted text from consent"
                        f" elements:\n{consent_text}\n\n"
                        "Return a detailed JSON object with"
                        " categories, partners, purposes, and"
                        " any manage options button."
                    ),
                    screenshot=screenshot,
                ),
                timeout=30,
            )
            log.end_timer(
                "vision-extraction",
                "Vision extraction complete",
            )

            parsed = self._parse_response(
                response, _ConsentExtractionResponse
            )
            if parsed:
                result = _to_domain(parsed, consent_text)
                log.info(
                    "Extraction result",
                    {
                        "categories": len(result.categories),
                        "partners": len(result.partners),
                        "purposes": len(result.purposes),
                        "hasManageOptions": result.has_manage_options,
                        "claimedPartnerCount": result.claimed_partner_count,
                    },
                )
                return result

            # Fallback: manual parse from text
            log.debug("Structured parse failed, trying text fallback")
            return _parse_text_fallback(
                response.text, consent_text
            )
        except Exception as error:
            log.end_timer(
                "vision-extraction",
                "Vision extraction failed",
            )
            error_msg = errors.get_error_message(error)
            if isinstance(error, asyncio.TimeoutError):
                log.warn(
                    "Consent extraction timed out after 30s",
                )
            else:
                log.error(
                    "Consent extraction failed",
                    {"error": error_msg},
                )
            return consent.ConsentDetails.empty(
                consent_text[:5000],
                claimed_partner_count=_extract_partner_count_from_text(
                    consent_text
                ),
            )


# ── Helpers ─────────────────────────────────────────────────────

# Patterns that match "We and our 1467 partners", "842 vendors",
# "sharing data with 500+ partners", etc.  The first capture
# group is the numeric count.
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


def _extract_partner_count_from_text(
    text: str,
) -> int | None:
    """Extract a claimed partner/vendor count from raw consent text.

    Searches for common phrases like "We and our 1467 partners"
    and returns the highest number found (to handle cases where
    multiple counts appear, e.g. sub-sections).

    Args:
        text: Raw consent dialog text extracted from the DOM.

    Returns:
        The claimed partner count, or ``None`` if not found.
    """
    counts: list[int] = []
    for pattern in _PARTNER_COUNT_PATTERNS:
        for match in pattern.finditer(text):
            try:
                raw_num = match.group(1).replace(",", "").replace(".", "")
                num = int(raw_num)
                # Ignore tiny numbers ("our 2 partners") —
                # these are usually incidental phrases.
                if num >= 5:
                    counts.append(num)
            except (ValueError, IndexError):
                continue
    return max(counts) if counts else None


def _to_domain(
    r: _ConsentExtractionResponse,
    raw_text: str,
) -> consent.ConsentDetails:
    """Convert structured response to domain model.

    Args:
        r: Parsed LLM response.
        raw_text: Raw consent text from the page.

    Returns:
        Domain ``ConsentDetails`` instance.
    """
    return consent.ConsentDetails(
        has_manage_options=r.hasManageOptions,
        manage_options_selector=r.manageOptionsSelector,
        categories=[
            consent.ConsentCategory(
                name=c.name,
                description=c.description,
                required=c.required,
            )
            for c in r.categories
        ],
        partners=[
            consent.ConsentPartner(
                name=p.name,
                purpose=p.purpose,
                data_collected=p.dataCollected,
            )
            for p in r.partners
        ],
        purposes=r.purposes,
        raw_text=raw_text[:5000],
        claimed_partner_count=(
            r.claimedPartnerCount
            or _extract_partner_count_from_text(raw_text)
        ),
    )


def _parse_text_fallback(
    text: str | None,
    raw_text: str,
) -> consent.ConsentDetails:
    """Parse raw LLM text when structured output fails.

    Args:
        text: Raw LLM response text.
        raw_text: Raw consent text from the page.

    Returns:
        Parsed ``ConsentDetails``.
    """
    raw = json_parsing.load_json_from_text(text)
    if isinstance(raw, dict):
        return consent.ConsentDetails(
            has_manage_options=raw.get(
                "hasManageOptions", False
            ),
            manage_options_selector=raw.get(
                "manageOptionsSelector"
            ),
            categories=[
                consent.ConsentCategory(
                    name=c.get("name", ""),
                    description=c.get("description", ""),
                    required=c.get("required", False),
                )
                for c in raw.get("categories", [])
            ],
            partners=[
                consent.ConsentPartner(
                    name=p.get("name", ""),
                    purpose=p.get("purpose", ""),
                    data_collected=p.get(
                        "dataCollected", []
                    ),
                )
                for p in raw.get("partners", [])
            ],
            purposes=raw.get("purposes", []),
            raw_text=raw_text[:5000],
            claimed_partner_count=(
                raw.get("claimedPartnerCount")
                or _extract_partner_count_from_text(raw_text)
            ),
        )
    return consent.ConsentDetails.empty(raw_text[:5000])


async def _extract_consent_text(
    page: async_api.Page,
) -> str:
    """Extract text from consent-related DOM elements.

    Combines text from main-page selectors and consent
    iframes into a single string.

    Args:
        page: Playwright page to extract from.

    Returns:
        Combined consent text, truncated to 50 000 chars.
    """
    main_page_text: str = await page.evaluate(
        _EXTRACT_CONSENT_JS
    )

    iframe_texts: list[str] = []
    consent_keywords = (
        "consent",
        "onetrust",
        "cookiebot",
        "sourcepoint",
        "trustarc",
        "didomi",
        "quantcast",
        "cmp",
        "gdpr",
        "privacy",
    )
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        frame_url = frame.url.lower()
        if any(kw in frame_url for kw in consent_keywords):
            try:
                iframe_text: str = await frame.evaluate(
                    _EXTRACT_IFRAME_JS
                )
                if iframe_text:
                    iframe_texts.append(
                        f"[CONSENT IFRAME]:\n{iframe_text}"
                    )
            except Exception as exc:
                log.debug(f"Failed to extract iframe text from {frame.url}: {exc}")

    all_texts = [
        t for t in [*iframe_texts, main_page_text] if t
    ]
    log.debug("Consent text extraction", {
        "mainTextChars": len(main_page_text),
        "iframeCount": len(iframe_texts),
        "totalChars": sum(len(t) for t in all_texts),
    })
    return "\n\n---\n\n".join(all_texts)[:50000]
