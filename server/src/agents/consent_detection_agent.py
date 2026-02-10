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
on websites that block access to content until the user takes \
an action.

You will receive:
1. A **screenshot** of the page as it currently appears
2. **HTML snippets** extracted from the page

Your task is to determine whether a blocking overlay is \
present and, if so, identify the EXACT button to click to \
dismiss or accept it.

# What to look for

Scan the ENTIRE screenshot — top, bottom, corners, and \
center — for any of these overlay types:

1. **Cookie / Consent Banners** — ask the user to accept \
or reject tracking. Look for buttons labelled "Accept", \
"Accept All", "Allow", "OK", "Agree", "I Accept", \
"Accept additional cookies", etc.

2. **Sign-in / Account Prompts** — block content until \
the user logs in. Find the DISMISS option ("Maybe Later", \
"Not Now", "Skip", "No Thanks", "Close", "X"). \
NEVER select the sign-in or register button.

3. **Newsletter / Email Signup Popups** — dismiss with \
"No Thanks", "Close", "X", "Maybe Later", "Skip".

4. **Paywalls / Subscription Walls** — look for \
"Continue reading", "Read for free", "Close", "X".

5. **Age Verification Gates** — "I am over 18", "Yes", \
"Enter", "Confirm".

# What to IGNORE (return found=false)

- Confirmation messages ("Your preferences have been saved")
- "Thank you" banners that need no action
- Small notification toasts that auto-dismiss
- Informational banners that do not block content

The key question: does this overlay BLOCK access to the \
page until the user makes a choice?

# How to choose the selector

The selector MUST be a **standard CSS selector** that can \
be passed directly to `document.querySelector()`. \
DO NOT use pseudo-selectors like `:has-text()` or \
`:contains()` — these are not valid CSS.

Selector priority (use the first one that uniquely \
identifies the button):

1. **ID** — `#accept-cookies`, `#onetrust-accept-btn-handler`
2. **data attribute** — `[data-action="accept"]`, \
`[data-testid="accept-button"]`
3. **ARIA label** — `[aria-label="Accept cookies"]`, \
`button[aria-label="Accept additional cookies"]`
4. **Unique class** — `button.accept-btn`, `.sp_choice_type_11`
5. **Combination** — `div.consent-banner button.primary`

If none of the above can uniquely identify the button, \
set `selector` to null and put the EXACT visible button \
text in `buttonText` — the click handler will fall back \
to text matching.

# buttonText field

ALWAYS set `buttonText` to the EXACT text shown on the \
button in the screenshot (e.g. "Accept additional cookies", \
"I Accept", "Accept All"). This is used as a fallback if \
the CSS selector fails.

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
    max_retries = 5
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
