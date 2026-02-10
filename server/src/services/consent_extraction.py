"""
Consent details extraction using LLM vision.

Extracts detailed information about cookie categories, partners,
and data collection purposes from consent dialogs using the
Microsoft Agent Framework ChatAgent with vision.
"""

from __future__ import annotations

import json
import re

from playwright import async_api

from src.agents.chat_agent import get_chat_agent_service
from src.agents.config import AGENT_CONSENT_EXTRACTION
from src.prompts import consent_extraction
from src.types import consent
from src.utils import errors, logger

log = logger.create_logger("Consent-Extract")


async def extract_consent_details(
    page: async_api.Page, screenshot: bytes
) -> consent.ConsentDetails:
    """
    Extract detailed consent information from a cookie preferences panel.
    Uses LLM vision to analyse the screenshot and extract structured data.
    """
    agent_service = get_chat_agent_service()
    if not agent_service.is_configured:
        log.warn("LLM not configured, skipping consent extraction")
        return consent.ConsentDetails(
            has_manage_options=False,
            manage_options_selector=None,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="",
        )

    log.info("Extracting consent details from page...")

    log.start_timer("text-extraction")

    # Extract text from main page consent elements
    main_page_text = await page.evaluate(
        """() => {
            const selectors = [
                '[class*="cookie"]', '[class*="consent"]', '[class*="privacy"]',
                '[class*="gdpr"]', '[id*="cookie"]', '[id*="consent"]',
                '[role="dialog"]', '[class*="modal"]', '[class*="banner"]',
                '[class*="overlay"]', '[class*="cmp"]', '[class*="tcf"]',
                '[class*="vendor"]', '[class*="partner"]',
            ];
            const elements = [];
            for (const sel of selectors) {
                document.querySelectorAll(sel).forEach(el => {
                    const text = el.innerText?.trim();
                    if (text && text.length > 10 && text.length < 15000) {
                        elements.push(text);
                    }
                });
            }
            document.querySelectorAll('table').forEach(table => {
                const text = table.innerText?.trim();
                if (text && (text.toLowerCase().includes('partner') ||
                    text.toLowerCase().includes('vendor') ||
                    text.toLowerCase().includes('cookie') ||
                    text.toLowerCase().includes('purpose'))) {
                    elements.push(text);
                }
            });
            document.querySelectorAll('ul, ol').forEach(list => {
                const text = list.innerText?.trim();
                const parentText = list.parentElement?.innerText?.toLowerCase() || '';
                if (text && text.length > 50 &&
                    (parentText.includes('partner') ||
                     parentText.includes('vendor') ||
                     parentText.includes('third part'))) {
                    elements.push('PARTNER LIST:\\n' + text);
                }
            });
            return [...new Set(elements)].join('\\n\\n---\\n\\n');
        }"""
    )

    # Extract from consent iframes
    iframe_texts: list[str] = []
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        frame_url = frame.url.lower()
        consent_keywords = (
            "consent", "onetrust", "cookiebot", "sourcepoint",
            "trustarc", "didomi", "quantcast", "cmp", "gdpr", "privacy",
        )
        if any(kw in frame_url for kw in consent_keywords):
            try:
                iframe_text = await frame.evaluate(
                    """() => {
                        const text = document.body?.innerText?.trim();
                        return text && text.length > 50 ? text : '';
                    }"""
                )
                if iframe_text:
                    iframe_texts.append(f"[CONSENT IFRAME]:\n{iframe_text}")
            except Exception:
                pass

    # Combine text
    all_texts = [t for t in [*iframe_texts, main_page_text] if t]
    consent_text = "\n\n---\n\n".join(all_texts)[:50000]

    log.end_timer("text-extraction", "Text extraction complete")
    log.debug("Extracted consent text", {"length": len(consent_text)})

    log.start_timer("vision-extraction")
    log.info("Analysing consent dialog with vision...")

    try:
        content = await agent_service.complete_with_vision(
            system_prompt=consent_extraction.CONSENT_EXTRACTION_SYSTEM_PROMPT,
            user_text=consent_extraction.build_consent_extraction_user_prompt(
                consent_text
            ),
            screenshot=screenshot,
            agent_name=AGENT_CONSENT_EXTRACTION,
            max_tokens=4000,
            retry_context="Consent extraction",
        )

        log.end_timer("vision-extraction", "Vision extraction complete")

        content = content or "{}"
        json_str = content.strip()
        if json_str.startswith("```"):
            json_str = re.sub(r"```json?\n?", "", json_str)
            json_str = re.sub(r"```$", "", json_str).strip()

        raw = json.loads(json_str)

        result = consent.ConsentDetails(
            has_manage_options=raw.get("hasManageOptions", False),
            manage_options_selector=raw.get("manageOptionsSelector"),
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
                    data_collected=p.get("dataCollected", []),
                )
                for p in raw.get("partners", [])
            ],
            purposes=raw.get("purposes", []),
            raw_text=consent_text[:5000],
        )

        log.success(
            "Consent details extracted",
            {
                "categories": len(result.categories),
                "partners": len(result.partners),
                "purposes": len(result.purposes),
            },
        )

        return result
    except Exception as error:
        log.error("Consent extraction failed", {"error": errors.get_error_message(error)})
        return consent.ConsentDetails(
            has_manage_options=False,
            manage_options_selector=None,
            categories=[],
            partners=[],
            purposes=[],
            raw_text=consent_text[:5000],
        )
