"""Consent detection agent using LLM vision.

Analyses screenshots and HTML to detect blocking overlays
(cookie consent, sign-in walls, etc.) and locate dismiss
buttons.  Returns structured ``CookieConsentDetection``.
"""

from __future__ import annotations

import re
from typing import Literal

import pydantic

from src.agents import base, config
from src.models import consent
from src.utils import errors, logger
from src.utils.json_parsing import load_json_from_text

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
You are an expert web analyst. Your job is to look at a \
screenshot of a webpage and determine whether there is \
any dialog, banner, overlay, or prompt that needs to be \
dismissed or accepted before the page can be fully used.

You will receive:
1. A **screenshot** of the page as it currently appears
2. **HTML snippets** extracted from the page

# Step 1 — Carefully examine the screenshot

Look at the ENTIRE screenshot — top, bottom, every \
corner, and the center. Look for:

- Any modal dialog or overlay covering part of the page
- Any banner or bar (top, bottom, or floating) with \
  buttons or links
- Any prompt asking the user to take an action
- Any semi-transparent backdrop or dimmed background \
  suggesting a modal is open

Pay special attention to how the page content appears. \
If the main article or content is partially obscured, \
dimmed, or has a backdrop overlay, there is likely a \
blocking dialog present.

# Step 2 — Classify what you found

If you see an overlay, classify it as one of:

1. **cookie-consent** — Cookie banners, privacy notices, \
   tracking consent. These can appear ANYWHERE: full-page \
   modals, bottom bars, top banners, floating panels, \
   side drawers. They do NOT need to block content to \
   count — even a small bar counts.

2. **sign-in** — The page is asking the user to sign in, \
   register, or create an account. You must find the \
   DISMISS or SKIP option, NOT the sign-in button.

3. **newsletter** — Email signup or notification popups.

4. **paywall** — Content is gated behind a subscription \
   or payment wall.

5. **age-verification** — Age confirmation gates.

6. **other** — Anything else that needs dismissing.

**Priority:** If you see BOTH a blocking dialog (e.g. \
sign-in prompt covering the page) AND a non-blocking \
banner (e.g. cookie bar at the bottom), report the \
BLOCKING one first — it must be dealt with before the \
non-blocking one can be addressed.

# Step 3 — Read the EXACT button or link text

This is the most critical step. Look at the screenshot \
very carefully and read the EXACT text on the button or \
link that should be clicked to dismiss or accept.

**Do NOT guess or use generic text.** Read the actual \
words visible in the screenshot. The text could be \
anything — it is not limited to common phrases. Examples \
of real button/link text seen on websites:

- "Accept additional cookies"
- "Maybe later"
- "Yes, I agree"
- "Got it"
- "I Accept"
- "No thanks, take me to the site"
- "Continue without accepting"
- "Accept & close"
- "That's OK"
- "ACCEPT ALL"
- "I'm OK with that"
- "Agree and close"
- "Not now"
- "Allow all"
- "Fine by me"
- "OK, I understand"
- "Skip for now"
- "Close and accept"
- "Sounds good"
- "Continue to site"
- "I consent"

Put this EXACT text (as shown in the screenshot, \
preserving case) in the `buttonText` field. This is \
the primary way the button will be found and clicked.

# Step 4 — Find a CSS selector (if possible)

Look in the HTML snippets for the element matching the \
button you identified visually. The selector MUST be a \
**standard CSS selector** valid for `document.\
querySelector()`. DO NOT use `:has-text()` or \
`:contains()` — these are not valid CSS.

IMPORTANT: Consent dismiss buttons and accept links are \
almost always **non-navigating** elements. They use \
`href="javascript:void(0)"`, `href="#"`, or have no \
href at all — they close the dialog via JavaScript. \
If you see a link with a real URL (like `/sign-in` or \
`/register`), it is NOT the dismiss button — look for \
the skip/close/later option instead.

Selector priority:
1. **ID** — `#accept-cookies`
2. **data attribute** — `[data-action="accept"]`
3. **ARIA label** — `[aria-label="Accept cookies"]`
4. **Unique class** — `button.accept-btn`
5. **Combination** — `div.consent-banner button.primary`

If you cannot find a reliable CSS selector in the HTML, \
set `selector` to null. The `buttonText` will be used \
instead.

# What to IGNORE (return found=false)

- Confirmation messages ("Your preferences have been saved")
- "Thank you" banners that need no action
- Small notification toasts that auto-dismiss
- Purely informational banners with no actionable buttons
- Banners that have already been dismissed
- Navigation menus, footers, or page chrome

Return ONLY a JSON object matching the required schema."""


# ── Agent class ─────────────────────────────────────────────────

class ConsentDetectionAgent(base.BaseAgent):
    """Vision agent that detects blocking overlays.

    Sends a screenshot + relevant HTML to the LLM and
    returns a typed ``CookieConsentDetection`` result.
    """

    agent_name = config.AGENT_CONSENT_DETECTION
    instructions = _INSTRUCTIONS
    max_tokens = 1000
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
                    "Look at this screenshot carefully."
                    " Is there any dialog, banner, overlay,"
                    " or prompt visible that needs to be"
                    " dismissed or accepted?\n\n"
                    "If yes, read the EXACT text on the"
                    " button or link to click — do not"
                    " guess, read it from the image.\n\n"
                    "Then look in these HTML snippets for"
                    " a CSS selector matching that element"
                    " (set selector to null if unsure):\n\n"
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
    raw = load_json_from_text(text)
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

    Uses a two-tier approach:
    1. High-priority patterns (consent/modal-specific) are
       extracted first and allocated most of the budget.
    2. Low-priority patterns (generic buttons, links,
       sections) fill the remaining budget.

    Args:
        full_html: Complete page HTML.

    Returns:
        Truncated relevant HTML for the LLM prompt.
    """
    max_length = 150000

    # Tier 1 — consent-specific and overlay-specific HTML.
    # These are the elements most likely to contain the
    # information the LLM needs.
    high_priority_patterns = [
        r"<div[^>]*(?:cookie|consent|gdpr|privacy|banner"
        r"|modal|popup|overlay|notice|cmp)[^>]*>"
        r"[\s\S]*?</div>",
        r"<div[^>]*(?:sign-?in|login|auth|account"
        r"|register|subscribe|newsletter|prompt"
        r"|upsell|gate)[^>]*>[\s\S]*?</div>",
        r"<(?:dialog|aside)[^>]*>[\s\S]*?</(?:dialog"
        r"|aside)>",
        r'<div[^>]*(?:role=["\']dialog["\']'
        r"|aria-modal)[^>]*>[\s\S]*?</div>",
        r"<div[^>]*(?:position:\s*fixed"
        r"|position:\s*sticky)[^>]*>[\s\S]*?</div>",
        r'<[^>]*(?:class|id)=["\'][^"\']*(?:close'
        r"|dismiss|skip|later)[^\"']*[\"'][^>]*>"
        r"[\\s\\S]*?</[^>]+>",
    ]

    # Tier 2 — generic elements.  These provide supporting
    # context (e.g. all visible buttons) but are much noisier.
    low_priority_patterns = [
        r"<button[^>]*>[\s\S]*?</button>",
        r"<a[^>]*>[\s\S]*?</a>",
        r"<section[^>]*>[\s\S]*?</section>",
    ]

    high: list[str] = []
    for pat in high_priority_patterns:
        found = re.findall(pat, full_html, re.IGNORECASE)
        high.extend(found[:20])

    high_text = "\n".join(high)
    if len(high_text) >= max_length:
        return high_text[:max_length]

    # Fill remaining budget with lower-priority matches.
    low: list[str] = []
    for pat in low_priority_patterns:
        found = re.findall(pat, full_html, re.IGNORECASE)
        low.extend(found[:10])

    combined = high_text + "\n" + "\n".join(low)
    if combined.strip():
        return combined[:max_length]

    return full_html[:100000]


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
        (r">Accept All<", None, "Accept All"),
        (r">Accept Cookies<", None, "Accept Cookies"),
        (r">I Agree<", None, "I Agree"),
        (r">Agree<", None, "Agree"),
    ]

    for pattern, selector, *rest in consent_patterns:
        if re.search(pattern, html, re.IGNORECASE):
            btn_text = rest[0] if rest else "Accept"
            log.success(
                "Found overlay via HTML pattern matching",
                {"selector": selector, "buttonText": btn_text},
            )
            return consent.CookieConsentDetection(
                found=True,
                overlay_type="cookie-consent",
                selector=selector,
                button_text=btn_text,
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
