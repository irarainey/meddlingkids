"""
Cookie consent banner detection using LLM vision.

Uses the Microsoft Agent Framework ChatAgent with vision to
analyse screenshots and find overlay dismiss buttons.
"""

from __future__ import annotations

import json
import re

from src.agents.chat_agent import get_chat_agent_service
from src.agents.config import AGENT_CONSENT_DETECTION
from src.prompts import consent_detection
from src.types import consent
from src.utils import errors, logger

log = logger.create_logger("Consent-Detect")


async def detect_cookie_consent(
    screenshot: bytes, html: str
) -> consent.CookieConsentDetection:
    """
    Detect blocking overlays (cookie consent, sign-in walls, etc.) using LLM vision.
    """
    agent_service = get_chat_agent_service()
    if not agent_service.is_configured:
        log.warn("LLM not configured, skipping consent detection")
        return consent.CookieConsentDetection(
            found=False,
            overlay_type=None,
            selector=None,
            button_text=None,
            confidence="low",
            reason="LLM not configured",
        )

    relevant_html = _extract_relevant_html(html)
    log.debug(
        "Extracted relevant HTML",
        {"originalLength": len(html), "extractedLength": len(relevant_html)},
    )

    log.start_timer("vision-detection")
    log.info("Analysing screenshot for overlays...")

    try:
        content = await agent_service.complete_with_vision(
            system_prompt=consent_detection.CONSENT_DETECTION_SYSTEM_PROMPT,
            user_text=consent_detection.build_consent_detection_user_prompt(
                relevant_html
            ),
            screenshot=screenshot,
            agent_name=AGENT_CONSENT_DETECTION,
            max_tokens=500,
            retry_context="Consent detection",
        )

        log.end_timer("vision-detection", "Vision analysis complete")

        content = content or "{}"
        json_str = content.strip()
        if json_str.startswith("```"):
            json_str = re.sub(r"```json?\n?", "", json_str)
            json_str = re.sub(r"```$", "", json_str).strip()

        raw = json.loads(json_str)
        result = consent.CookieConsentDetection(
            found=raw.get("found", False),
            overlay_type=raw.get("overlayType"),
            selector=raw.get("selector"),
            button_text=raw.get("buttonText"),
            confidence=raw.get("confidence", "low"),
            reason=raw.get("reason", ""),
        )

        if result.found:
            log.success(
                "Overlay detected",
                {
                    "type": result.overlay_type,
                    "selector": result.selector,
                    "confidence": result.confidence,
                },
            )
        else:
            log.info("No overlay detected", {"reason": result.reason})

        return result
    except Exception as error:
        error_msg = errors.get_error_message(error)

        if any(
            kw in error_msg
            for kw in ("filtered", "content_filter", "ResponsibleAIPolicyViolation")
        ):
            log.warn(
                "Content filtered by Azure OpenAI - trying HTML-only detection"
            )
            return _detect_from_html_only(relevant_html)

        log.error("Overlay detection failed", {"error": error_msg})
        return consent.CookieConsentDetection(
            found=False,
            overlay_type=None,
            selector=None,
            button_text=None,
            confidence="low",
            reason=f"Detection failed: {error_msg}",
        )


def _detect_from_html_only(html: str) -> consent.CookieConsentDetection:
    """Fallback detection using HTML patterns only (no vision)."""
    log.info("Attempting HTML-only overlay detection...")

    consent_patterns = [
        (r'id=["\']?onetrust-accept-btn-handler["\']?', "#onetrust-accept-btn-handler"),
        (r'id=["\']?accept-cookies["\']?', "#accept-cookies"),
        (r'id=["\']?CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll["\']?', "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"),
        (r'id=["\']?didomi-notice-agree-button["\']?', "#didomi-notice-agree-button"),
        (r'class=["\'][^"\']*sp_choice_type_11[^"\']*["\']?', "button.sp_choice_type_11"),
        (r'data-action=["\']?accept["\']?', '[data-action="accept"]'),
        (r'data-testid=["\']?accept-button["\']?', '[data-testid="accept-button"]'),
        (r'aria-label=["\'][^"\']*[Aa]ccept[^"\']*["\']', '[aria-label*="ccept"]'),
        (r">Accept All<", 'button:has-text("Accept All")'),
        (r">Accept Cookies<", 'button:has-text("Accept Cookies")'),
        (r">I Agree<", 'button:has-text("I Agree")'),
        (r">Agree<", 'button:has-text("Agree")'),
    ]

    for pattern, selector in consent_patterns:
        if re.search(pattern, html, re.IGNORECASE):
            log.success(
                "Found overlay via HTML pattern matching",
                {"selector": selector},
            )
            return consent.CookieConsentDetection(
                found=True,
                overlay_type="cookie-consent",
                selector=selector,
                button_text="Accept",
                confidence="medium",
                reason="Detected via HTML pattern matching (vision unavailable due to content filter)",
            )

    log.info("No overlay detected via HTML patterns")
    return consent.CookieConsentDetection(
        found=False,
        overlay_type=None,
        selector=None,
        button_text=None,
        confidence="low",
        reason="No overlay detected (HTML-only detection, vision unavailable due to content filter)",
    )


def _extract_relevant_html(full_html: str) -> str:
    """Extract only relevant HTML snippets for overlay analysis."""
    patterns = [
        r"<div[^>]*(?:cookie|consent|gdpr|privacy|banner|modal|popup|overlay)[^>]*>[\s\S]*?</div>",
        r"<div[^>]*(?:sign-?in|login|auth|account|register|subscribe|newsletter|prompt|upsell|gate)[^>]*>[\s\S]*?</div>",
        r"<(?:dialog|aside)[^>]*>[\s\S]*?</(?:dialog|aside)>",
        r'<div[^>]*(?:role=["\']dialog["\']|aria-modal)[^>]*>[\s\S]*?</div>',
        r"<div[^>]*(?:position:\s*fixed|position:\s*sticky)[^>]*>[\s\S]*?</div>",
        r"<button[^>]*>[\s\S]*?</button>",
        r"<a[^>]*>[\s\S]*?</a>",
        r'<[^>]*(?:class|id)=["\'][^"\']*(?:close|dismiss|skip|later)[^"\']*["\'][^>]*>[\s\S]*?</[^>]+>',
        r"<section[^>]*>[\s\S]*?</section>",
    ]

    matches: list[str] = []
    for pat in patterns:
        found = re.findall(pat, full_html, re.IGNORECASE)
        matches.extend(found[:15])

    relevant = "\n".join(matches)[:20000]
    return relevant or full_html[:15000]
