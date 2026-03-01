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
from src.agents.prompts import consent_extraction
from src.consent import constants, text_parser
from src.models import consent
from src.utils import errors, image, json_parsing, logger

log = logger.create_logger("ConsentExtractionAgent")


def _safe_partner(name: str, purpose: str, data_collected: list[str]) -> consent.ConsentPartner | None:
    """Build a ``ConsentPartner``, returning ``None`` when validation fails.

    The model validator rejects headline-like names (e.g.
    news article titles captured from surrounding page
    content).  This helper catches those rejections so the
    caller can silently skip the entry.
    """
    try:
        return consent.ConsentPartner(
            name=name,
            purpose=purpose,
            data_collected=data_collected,
        )
    except pydantic.ValidationError:
        log.debug("Rejected non-partner name", {"name": name})
        return None


# ── Required-category detection ─────────────────────────────

# Names that indicate the category is non-optional (must be
# accepted for the site to function).  Matched case-insensitively
# against category names returned by the LLM to deterministically
# correct the ``required`` flag — the LLM sets it inconsistently.
_REQUIRED_CATEGORY_RE = re.compile(
    r"(?:strictly\s+)?necessary"
    r"|essential"
    r"|required"
    r"|always\s+active",
    re.IGNORECASE,
)


def _is_required_category(name: str) -> bool:
    """Return ``True`` when *name* describes a required category.

    Matches common labels such as "Strictly necessary cookies",
    "Essential cookies", or "Required" — regardless of how the
    LLM set the ``required`` flag.
    """
    return bool(_REQUIRED_CATEGORY_RE.search(name))


# Pre-load JavaScript snippets evaluated in the browser.
_SCRIPTS_DIR = pathlib.Path(__file__).parent / "scripts"
_EXTRACT_CONSENT_JS = (_SCRIPTS_DIR / "extract_consent_text.js").read_text()
_EXTRACT_IFRAME_JS = (_SCRIPTS_DIR / "extract_iframe_text.js").read_text()
_GET_CONSENT_BOUNDS_JS = (_SCRIPTS_DIR / "get_consent_bounds.js").read_text()

# Timeout (seconds) for individual page.evaluate calls during
# consent text extraction.  Prevents hangs on unresponsive browsers.
_EVALUATE_TIMEOUT_SECONDS: int = 10
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
    dataCollected: list[str] = pydantic.Field(default_factory=list)


class _ConsentExtractionResponse(pydantic.BaseModel):
    """Schema pushed to the LLM via ``response_format``."""

    hasManageOptions: bool = False
    categories: list[_CategoryResponse] = pydantic.Field(default_factory=list)
    partners: list[_PartnerResponse] = pydantic.Field(default_factory=list)
    purposes: list[str] = pydantic.Field(default_factory=list)
    claimedPartnerCount: int | None = None


# ── Agent class ─────────────────────────────────────────────────


class ConsentExtractionAgent(base.BaseAgent):
    """Vision agent that extracts consent dialog details.

    Sends a screenshot + extracted page text to the LLM and
    returns typed ``ConsentDetails``.
    """

    agent_name = config.AGENT_CONSENT_EXTRACTION
    instructions = consent_extraction.INSTRUCTIONS
    max_tokens = 4096
    max_retries = 5
    response_model = _ConsentExtractionResponse

    async def extract(
        self,
        page: async_api.Page,
        screenshot: bytes,
        *,
        pre_captured_text: str | None = None,
        consent_bounds: tuple[int, int, int, int] | None = None,
    ) -> consent.ConsentDetails:
        """Extract consent details from a page screenshot.

        When *consent_bounds* is provided the screenshot is
        cropped to just the dialog area before sending to the
        LLM — this avoids content-filter rejections caused by
        surrounding page content (e.g. ads).

        A local regex-based parser always runs on the DOM text
        in parallel.  Its results are merged with the LLM
        output: the LLM takes priority for any field it
        populated; the local parse fills gaps the LLM missed
        and acts as the sole source if the LLM fails entirely.

        Args:
            page: Playwright page for DOM text extraction.
            screenshot: Raw JPEG screenshot bytes.
            pre_captured_text: DOM text captured while the
                consent dialog was still visible.  When
                provided, skips live DOM extraction (the
                dialog may already be dismissed).
            consent_bounds: ``(left, top, right, bottom)``
                pixel region to crop the screenshot to before
                sending it to the LLM.

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
        log.end_timer("text-extraction", "Text extraction complete")
        log.debug(
            "Extracted consent text",
            {"length": len(consent_text)},
        )

        # ── Local text parse (always runs) ──────────────
        local_result = text_parser.parse_consent_text(consent_text)

        # ── Crop screenshot to dialog area ──────────────
        llm_screenshot = screenshot
        if consent_bounds and screenshot:
            try:
                llm_screenshot = image.crop_jpeg(screenshot, consent_bounds)
                log.info(
                    "Screenshot cropped to consent dialog",
                    {
                        "originalBytes": len(screenshot),
                        "croppedBytes": len(llm_screenshot),
                        "bounds": consent_bounds,
                    },
                )
            except Exception as crop_err:
                log.warn(
                    "Screenshot cropping failed — using original",
                    {"error": str(crop_err)},
                )
                llm_screenshot = screenshot

        # ── LLM vision extraction ───────────────────────
        log.start_timer("vision-extraction")
        log.info("Analysing consent dialog with vision...")

        vision_user_text = (
            "Analyze this cookie consent dialog"
            " screenshot and extracted text to"
            " find ALL information about tracking,"
            " partners, and data collection.\n\n"
            "Extracted text from consent"
            f" elements:\n{consent_text}\n\n"
            "Return a detailed JSON object with"
            " categories, partners, purposes, and"
            " any manage options button."
        )

        vision_timeout = 30
        max_vision_attempts = 2
        last_error: Exception | None = None

        for attempt in range(1, max_vision_attempts + 1):
            try:
                response = await asyncio.wait_for(
                    self._complete_vision(
                        user_text=vision_user_text,
                        screenshot=llm_screenshot,
                    ),
                    timeout=vision_timeout,
                )
                log.end_timer(
                    "vision-extraction",
                    "Vision extraction complete",
                )

                parsed = self._parse_response(response, _ConsentExtractionResponse)
                if parsed:
                    llm_result = _to_domain(parsed, consent_text)
                    result = _merge_results(llm_result, local_result)
                    log.info(
                        "Extraction result (LLM + local merge)",
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
                llm_result = _parse_text_fallback(response.text, consent_text)
                return _merge_results(llm_result, local_result)
            except Exception as error:
                last_error = error
                error_msg = errors.get_error_message(error)
                is_timeout = isinstance(error, (asyncio.TimeoutError, TimeoutError)) or "timed out" in error_msg.lower()
                if is_timeout and attempt < max_vision_attempts:
                    log.warn(
                        "Vision timed out — retrying",
                        {"attempt": attempt, "error": error_msg},
                    )
                    continue
                if not is_timeout:
                    # Non-timeout error — break immediately.
                    break
                log.warn(
                    "Vision timed out — trying text-only LLM fallback",
                    {"attempt": attempt, "error": error_msg},
                )

        # ── Vision exhausted — try text-only LLM ───────
        log.end_timer(
            "vision-extraction",
            "Vision extraction failed",
        )
        if last_error is not None:
            error_msg = errors.get_error_message(last_error)
            is_timeout = isinstance(last_error, (asyncio.TimeoutError, TimeoutError)) or "timed out" in error_msg.lower()
            if is_timeout:
                text_result = await self._text_only_fallback(
                    consent_text,
                    local_result,
                )
                if text_result is not None:
                    return text_result
                log.info("Text-only fallback failed — using local parse only")
            else:
                log.error(
                    "Consent extraction failed — using local parse",
                    {"error": error_msg},
                )
            # LLM failed entirely — use the local parse as
            # the primary result, supplemented with partner
            # count from regex if the local parser missed it.
            if not local_result.claimed_partner_count:
                local_result.claimed_partner_count = _extract_partner_count_from_text(consent_text)
            return local_result

        # All vision attempts failed without raising — fall
        # back to the local parse result.
        if not local_result.claimed_partner_count:
            local_result.claimed_partner_count = _extract_partner_count_from_text(consent_text)
        return local_result

    async def _text_only_fallback(
        self,
        consent_text: str,
        local_result: consent.ConsentDetails,
    ) -> consent.ConsentDetails | None:
        """Attempt a text-only LLM call when vision times out.

        Tries up to two attempts with a 20 s timeout each.
        Returns the merged result on success, or ``None``
        when both attempts fail.
        """
        if not consent_text.strip():
            return None

        text_user_prompt = (
            "Analyze this cookie consent dialog"
            " text to find ALL information about"
            " tracking, partners, and data"
            " collection.\n\n"
            "Extracted text from consent"
            f" elements:\n{consent_text}\n\n"
            "Return a detailed JSON object with"
            " categories, partners, purposes,"
            " and any manage options button."
        )
        text_timeout = 20
        max_text_attempts = 2

        for attempt in range(1, max_text_attempts + 1):
            try:
                response = await asyncio.wait_for(
                    self._complete(
                        user_prompt=text_user_prompt,
                        response_model=_ConsentExtractionResponse,
                    ),
                    timeout=text_timeout,
                )
                parsed = self._parse_response(response, _ConsentExtractionResponse)
                if parsed:
                    llm_text_result = _to_domain(parsed, consent_text)
                    result = _merge_results(llm_text_result, local_result)
                    log.info(
                        "Text-only LLM fallback succeeded",
                        {
                            "categories": len(result.categories),
                            "partners": len(result.partners),
                            "purposes": len(result.purposes),
                            "claimedPartnerCount": result.claimed_partner_count,
                        },
                    )
                    return result

                # Structured parse failed — try manual JSON parse.
                text_fallback = _parse_text_fallback(response.text, consent_text)
                if text_fallback.categories or text_fallback.purposes:
                    return _merge_results(text_fallback, local_result)
            except Exception as fallback_err:
                error_msg = errors.get_error_message(fallback_err)
                is_timeout = (
                    isinstance(
                        fallback_err,
                        (asyncio.TimeoutError, TimeoutError),
                    )
                    or "timed out" in error_msg.lower()
                )
                if is_timeout and attempt < max_text_attempts:
                    log.warn(
                        "Text-only LLM fallback timed out — retrying",
                        {"attempt": attempt, "error": error_msg},
                    )
                    continue
                log.debug(
                    "Text-only LLM fallback failed",
                    {"attempt": attempt, "error": error_msg},
                )
        return None


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
        categories=[
            consent.ConsentCategory(
                name=c.name,
                description=c.description,
                required=c.required or _is_required_category(c.name),
            )
            for c in r.categories
        ],
        partners=[p for p in (_safe_partner(p.name, p.purpose, p.dataCollected) for p in r.partners) if p is not None],
        purposes=r.purposes,
        raw_text=raw_text[:5000],
        claimed_partner_count=(r.claimedPartnerCount or _extract_partner_count_from_text(raw_text)),
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
            has_manage_options=raw.get("hasManageOptions", False),
            categories=[
                consent.ConsentCategory(
                    name=c.get("name", ""),
                    description=c.get("description", ""),
                    required=c.get("required", False) or _is_required_category(c.get("name", "")),
                )
                for c in raw.get("categories", [])
            ],
            partners=[
                p
                for p in (
                    _safe_partner(
                        c.get("name", ""),
                        c.get("purpose", ""),
                        c.get("dataCollected", []),
                    )
                    for c in raw.get("partners", [])
                )
                if p is not None
            ],
            purposes=raw.get("purposes", []),
            raw_text=raw_text[:5000],
            claimed_partner_count=(raw.get("claimedPartnerCount") or _extract_partner_count_from_text(raw_text)),
        )
    return consent.ConsentDetails.empty(raw_text[:5000])


def _merge_results(
    llm: consent.ConsentDetails,
    local: consent.ConsentDetails,
) -> consent.ConsentDetails:
    """Merge LLM and local-parse results with union semantics.

    The LLM result is primary.  The local parser supplements
    it with any purposes or categories it found that the LLM
    missed.  This ensures that deterministic regex matches
    (which only fire when the consent-context gate has already
    confirmed the text is from a consent dialog) are never
    silently discarded.

    Scalars:

    * ``has_manage_options`` — ``True`` if either source
      detected the indicator.
    * ``claimed_partner_count`` — falls back to the local
      count when the LLM didn't extract one.

    Collections (purposes, categories):

    * Start with the LLM list.
    * Append any local-parser entries whose normalised names
      are not already present.

    Partners are taken from the LLM only — the local regex
    parser's partner extraction is too noisy for union.

    Args:
        llm: Result from the LLM vision extraction.
        local: Result from the local text parser.

    Returns:
        A ``ConsentDetails`` instance.
    """
    # ── Union purposes ──────────────────────────────────
    merged_purposes = list(llm.purposes)
    existing_lower = {p.lower() for p in merged_purposes}
    for p in local.purposes:
        if p.lower() not in existing_lower:
            merged_purposes.append(p)
            existing_lower.add(p.lower())

    # ── Union categories ────────────────────────────────
    merged_categories = list(llm.categories)
    existing_cat_names = {c.name.lower() for c in merged_categories}
    for c in local.categories:
        if c.name.lower() not in existing_cat_names:
            merged_categories.append(c)
            existing_cat_names.add(c.name.lower())

    return consent.ConsentDetails(
        has_manage_options=llm.has_manage_options or local.has_manage_options,
        categories=merged_categories,
        partners=llm.partners,
        purposes=merged_purposes,
        raw_text=llm.raw_text,
        claimed_partner_count=llm.claimed_partner_count or local.claimed_partner_count,
        consent_platform=llm.consent_platform or local.consent_platform,
    )


async def _extract_consent_text(
    page: async_api.Page,
) -> str:
    """Extract text from consent-related DOM elements.

    Combines text from main-page selectors and consent
    iframes into a single string.  Each evaluate call is
    individually bounded so an unresponsive browser cannot
    hang the entire extraction.

    Args:
        page: Playwright page to extract from.

    Returns:
        Combined consent text, truncated to 50 000 chars.
    """
    try:
        main_page_text: str = await asyncio.wait_for(
            page.evaluate(_EXTRACT_CONSENT_JS),
            timeout=_EVALUATE_TIMEOUT_SECONDS,
        )
    except (TimeoutError, Exception) as exc:
        log.warn("Main-page consent text extraction failed", {"error": str(exc)})
        main_page_text = ""

    iframe_texts: list[str] = []
    for frame in page.frames:
        if not constants.is_consent_frame(frame, page.main_frame):
            continue
        try:
            iframe_text: str = await asyncio.wait_for(
                frame.evaluate(_EXTRACT_IFRAME_JS),
                timeout=_EVALUATE_TIMEOUT_SECONDS,
            )
            if iframe_text:
                iframe_texts.append(f"[CONSENT IFRAME]:\n{iframe_text}")
        except Exception as exc:
            log.debug("Failed to extract iframe text", {"url": frame.url, "error": str(exc)})

    all_texts = [t for t in [*iframe_texts, main_page_text] if t]
    log.debug(
        "Consent text extraction",
        {
            "mainTextChars": len(main_page_text),
            "iframeCount": len(iframe_texts),
            "totalChars": sum(len(t) for t in all_texts),
        },
    )
    return "\n\n---\n\n".join(all_texts)[:50000]
