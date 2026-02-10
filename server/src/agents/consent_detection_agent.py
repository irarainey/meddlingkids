"""Consent detection agent using LLM vision.

Analyses screenshots and HTML to detect blocking overlays
(cookie consent, sign-in walls, etc.) and locate dismiss
buttons.  Returns structured ``CookieConsentDetection``.
"""

from __future__ import annotations

import re
from typing import Literal

import pydantic

from src.agents.base import BaseAgent
from src.agents.config import AGENT_CONSENT_DETECTION
from src.types import consent
from src.utils import errors, logger

log = logger.create_logger("ConsentDetectionAgent")


# ── Structured output model ────────────────────────────────────

class _ConsentDetectionResponse(pydantic.BaseModel):
    """Schema pushed to the LLM via ``response_format``."""

    found: bool
    overlayType: (
        Literal[
            "cookie-consent",
            "sign-in",
            "newsletter",
            "paywall",
            "age-verification",
            "other",
        ]
        | None
    ) = None
    selector: str | None = None
    buttonText: str | None = None
    confidence: Literal["high", "medium", "low"] = "low"
    reason: str = ""


# ── System prompt ───────────────────────────────────────────────

_INSTRUCTIONS = """\
You are an expert at detecting overlays, banners, and dialogs \
on websites that require user DECISION or ACTION before full \
access to content.

Your task is to analyze the screenshot and HTML to find \
elements that REQUIRE user interaction to:
- Accept or reject cookies/tracking
- Dismiss a blocking popup/modal
- Continue past a gate or wall
- Make a choice (accept, decline, sign in, etc.)

Look for these types (check the entire page, including \
corners, top, bottom, and center):

1. **Cookie/Consent Banners that ASK for consent**:
   - Accept buttons: "Accept All", "Accept", "Allow", \
"OK", "Agree", "I Accept"
   - These request a DECISION from the user

2. **Sign-in / Account Prompts**:
   - Look for DISMISS options: "Maybe Later", "Not Now", \
"Skip", "No Thanks", "Close", "X"
   - DO NOT click sign-in/register buttons — find the \
dismiss/skip option

3. **Newsletter / Email Signup Popups**:
   - Dismiss: "No Thanks", "Close", "X", "Maybe Later", \
"Skip"

4. **Paywalls / Subscription Walls**:
   - Look for: "Continue reading", "Read for free", \
"Close", "X"

5. **Age Verification Gates**:
   - "I am over 18", "Yes", "Enter", "Confirm"

IGNORE these (return found=false):
- "Thank you" or confirmation banners
- Informational banners with only a close/X button and \
no accept/reject choice
- Cookie preference confirmations
- Success messages — "Your preferences have been saved"
- Small notification toasts that auto-dismiss

The key distinction: Does the banner REQUIRE a user \
DECISION (accept/reject/choose), or is it just \
INFORMATIONAL (thank you/confirmation)?

For the selector, prefer:
1. Unique IDs: #accept-cookies
2. Data attributes: [data-action="accept"]
3. ARIA labels: [aria-label="Accept cookies"]
4. Button with specific text: button:has-text("Accept All")
5. Class-based selectors as last resort

Return ONLY a JSON object matching the required schema."""


# ── Agent class ─────────────────────────────────────────────────

class ConsentDetectionAgent(BaseAgent):
    """Vision agent that detects blocking overlays.

    Sends a screenshot + relevant HTML to the LLM and
    returns a typed ``CookieConsentDetection`` result.
    """

    agent_name = AGENT_CONSENT_DETECTION
    instructions = _INSTRUCTIONS
    max_tokens = 500
    max_retries = 3
    response_model = _ConsentDetectionResponse

    async def detect(
        self,
        screenshot: bytes,
        html: str,
    ) -> consent.CookieConsentDetection:
        """Detect overlays in the given screenshot and HTML.

        Args:
            screenshot: Raw PNG screenshot bytes.
            html: Full page HTML.

        Returns:
            A ``CookieConsentDetection`` with selector info.
        """
        relevant_html = _extract_relevant_html(html)
        log.debug(
            "Extracted relevant HTML",
            {
                "originalLength": len(html),
                "extractedLength": len(relevant_html),
            },
        )

        log.start_timer("vision-detection")
        log.info("Analysing screenshot for overlays...")

        try:
            response = await self._complete_vision(
                user_text=(
                    "Analyze this webpage screenshot and the"
                    " following HTML snippets to find any"
                    " blocking overlay (cookie consent,"
                    " sign-in prompt, newsletter popup,"
                    " etc.) and locate the button to dismiss"
                    " it or accept/continue.\n\n"
                    "Relevant HTML elements:\n"
                    f"{relevant_html}"
                ),
                screenshot=screenshot,
            )
            log.end_timer(
                "vision-detection",
                "Vision analysis complete",
            )

            parsed = self._parse_response(
                response, _ConsentDetectionResponse
            )
            if parsed:
                return _to_domain(parsed)

            # Fallback: manual parse from text
            return _parse_text_fallback(response.text)
        except Exception as error:
            msg = errors.get_error_message(error)
            if any(
                kw in msg
                for kw in (
                    "filtered",
                    "content_filter",
                    "ResponsibleAIPolicyViolation",
                )
            ):
                log.warn(
                    "Content filtered by Azure — trying"
                    " HTML-only detection"
                )
                return _detect_from_html_only(
                    relevant_html
                )

            log.error(
                "Overlay detection failed",
                {"error": msg},
            )
            return consent.CookieConsentDetection.not_found(
                f"Detection failed: {msg}"
            )


# ── Helper functions ────────────────────────────────────────────

def _to_domain(
    r: _ConsentDetectionResponse,
) -> consent.CookieConsentDetection:
    """Convert structured response to domain model.

    Args:
        r: Parsed LLM response.

    Returns:
        Domain ``CookieConsentDetection`` instance.
    """
    return consent.CookieConsentDetection(
        found=r.found,
        overlay_type=r.overlayType,
        selector=r.selector,
        button_text=r.buttonText,
        confidence=r.confidence,
        reason=r.reason,
    )


def _parse_text_fallback(
    text: str | None,
) -> consent.CookieConsentDetection:
    """Parse raw text when structured output fails.

    Args:
        text: Raw LLM response text.

    Returns:
        Parsed ``CookieConsentDetection``.
    """
    raw = BaseAgent._load_json_from_text(text)
    if isinstance(raw, dict):
        return consent.CookieConsentDetection(
            found=raw.get("found", False),
            overlay_type=raw.get("overlayType"),
            selector=raw.get("selector"),
            button_text=raw.get("buttonText"),
            confidence=raw.get("confidence", "low"),
            reason=raw.get("reason", ""),
        )
    return consent.CookieConsentDetection.not_found(
        "Failed to parse detection response"
    )


def _extract_relevant_html(full_html: str) -> str:
    """Extract HTML snippets likely related to overlays.

    Args:
        full_html: Complete page HTML.

    Returns:
        Truncated relevant HTML for the LLM prompt.
    """
    patterns = [
        r"<div[^>]*(?:cookie|consent|gdpr|privacy|banner"
        r"|modal|popup|overlay)[^>]*>[\s\S]*?</div>",
        r"<div[^>]*(?:sign-?in|login|auth|account"
        r"|register|subscribe|newsletter|prompt"
        r"|upsell|gate)[^>]*>[\s\S]*?</div>",
        r"<(?:dialog|aside)[^>]*>[\s\S]*?</(?:dialog"
        r"|aside)>",
        r'<div[^>]*(?:role=["\']dialog["\']'
        r"|aria-modal)[^>]*>[\s\S]*?</div>",
        r"<div[^>]*(?:position:\s*fixed"
        r"|position:\s*sticky)[^>]*>[\s\S]*?</div>",
        r"<button[^>]*>[\s\S]*?</button>",
        r"<a[^>]*>[\s\S]*?</a>",
        r'<[^>]*(?:class|id)=["\'][^"\']*(?:close'
        r"|dismiss|skip|later)[^\"']*[\"'][^>]*>"
        r"[\\s\\S]*?</[^>]+>",
        r"<section[^>]*>[\s\S]*?</section>",
    ]

    matches: list[str] = []
    for pat in patterns:
        found = re.findall(pat, full_html, re.IGNORECASE)
        matches.extend(found[:15])

    relevant = "\n".join(matches)[:20000]
    return relevant or full_html[:15000]


def _detect_from_html_only(
    html: str,
) -> consent.CookieConsentDetection:
    """Fallback detection using HTML patterns only.

    Args:
        html: Relevant HTML snippets.

    Returns:
        Detection result based on regex patterns.
    """
    log.info("Attempting HTML-only overlay detection...")

    consent_patterns = [
        (
            r'id=["\']?onetrust-accept-btn-handler["\']?',
            "#onetrust-accept-btn-handler",
        ),
        (
            r'id=["\']?accept-cookies["\']?',
            "#accept-cookies",
        ),
        (
            r'id=["\']?CybotCookiebotDialogBody'
            r'LevelButtonLevelOptinAllowAll["\']?',
            "#CybotCookiebotDialogBody"
            "LevelButtonLevelOptinAllowAll",
        ),
        (
            r'id=["\']?didomi-notice-agree-button["\']?',
            "#didomi-notice-agree-button",
        ),
        (
            r'class=["\'][^"\']*sp_choice_type_11'
            r'[^"\']*["\']?',
            "button.sp_choice_type_11",
        ),
        (
            r'data-action=["\']?accept["\']?',
            '[data-action="accept"]',
        ),
        (
            r'data-testid=["\']?accept-button["\']?',
            '[data-testid="accept-button"]',
        ),
        (
            r'aria-label=["\'][^"\']*[Aa]ccept'
            r'[^"\']*["\']',
            '[aria-label*="ccept"]',
        ),
        (r">Accept All<", 'button:has-text("Accept All")'),
        (
            r">Accept Cookies<",
            'button:has-text("Accept Cookies")',
        ),
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
                reason=(
                    "Detected via HTML pattern matching"
                    " (vision unavailable due to content"
                    " filter)"
                ),
            )

    log.info("No overlay detected via HTML patterns")
    return consent.CookieConsentDetection.not_found(
        "No overlay detected (HTML-only detection,"
        " vision unavailable due to content filter)"
    )
