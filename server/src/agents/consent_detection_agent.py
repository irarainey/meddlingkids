"""Consent detection agent using LLM vision.

Vision-only overlay detection: send a screenshot to the LLM
and get back presence, type, certainty percentage, and the
exact button text to click.  No HTML is sent to the LLM —
the click module handles finding the element by button text.

Returns structured ``CookieConsentDetection``.
"""

from __future__ import annotations

from typing import Literal

import pydantic

from src.agents import base, config
from src.models import consent
from src.utils import errors, json_parsing, logger

log = logger.create_logger("ConsentDetectionAgent")

# Minimum certainty (0-100) required before we treat the
# detection as a real overlay worth clicking.
_CERTAINTY_THRESHOLD = 40


# -- Structured output model ------------------------------------------

class _VisionDetectionResponse(pydantic.BaseModel):
    """LLM response schema -- vision-only overlay detection."""

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
    buttonText: str | None = None
    certainty: int = 0  # 0-100
    reason: str = ""


# -- System prompt -----------------------------------------------------

_INSTRUCTIONS = """\
You are an expert web analyst. Your ONLY job is to look \
at a screenshot of a webpage and determine whether there \
is any dialog, banner, overlay, or prompt that needs to \
be dismissed or accepted before the page can be fully used.

You will receive ONLY a screenshot -- no HTML.

# Step 1 -- Carefully examine the screenshot

Look at the ENTIRE screenshot -- top, bottom, every \
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

# Step 2 -- Classify what you found

If you see an overlay, classify it as one of:

1. **cookie-consent** -- Cookie banners, privacy notices, \
   tracking consent. These can appear ANYWHERE: full-page \
   modals, bottom bars, top banners, floating panels, \
   side drawers. They do NOT need to block content to \
   count -- even a small bar counts.

2. **sign-in** -- The page is asking the user to sign in, \
   register, or create an account. You must find the \
   DISMISS or SKIP option, NOT the sign-in button.

3. **newsletter** -- Email signup or notification popups.

4. **paywall** -- Content is gated behind a subscription \
   or payment wall.

5. **age-verification** -- Age confirmation gates.

6. **other** -- Anything else that needs dismissing.

**Priority:** If you see BOTH a blocking dialog (e.g. \
sign-in prompt covering the page) AND a non-blocking \
banner (e.g. cookie bar at the bottom), report the \
BLOCKING one first -- it must be dealt with before the \
non-blocking one can be addressed.

# Step 3 -- Rate your certainty (0-100)

How certain are you that there is a dismissable overlay?

- **90-100** -- Unambiguous modal / banner with clear \
  dismiss buttons
- **70-89** -- Very likely an overlay but visually subtle
- **50-69** -- Probably an overlay but could be normal \
  page content
- **30-49** -- Uncertain -- might be a page element, not \
  an overlay
- **0-29** -- Very unlikely to be an overlay

# Step 4 -- Read the EXACT button or link text

This is the most critical step. Look at the screenshot \
very carefully and read the EXACT text on the button or \
link that should be clicked to dismiss the overlay.

**IMPORTANT -- Preferred button priority for cookie-consent \
dialogs:**

1. **MOST PREFERRED** -- "Reject all", "Decline all", \
   "Refuse", "Deny", "Necessary only", \
   "Essential cookies only", "Continue without accepting"
2. **Acceptable** -- "Close", "Dismiss", "Not now", \
   "No thanks", "Skip", "Maybe later", \
   "Continue to site"
3. **LAST RESORT (only if no reject option exists)** -- \
   "Accept", "Accept all", "Agree", "Allow all", \
   "I Accept", "I consent"

Always choose the MOST PRIVACY-PRESERVING option visible \
in the screenshot. Only fall back to "Accept" buttons \
when no reject, decline, close, or dismiss option is \
available.

**Do NOT guess or use generic text.** Read the actual \
words visible in the screenshot. The text could be \
anything -- it is not limited to common phrases. Examples \
of real button/link text seen on websites:

- "Reject all"
- "Decline"
- "Necessary cookies only"
- "Continue without accepting"
- "No thanks, take me to the site"
- "Not now"
- "Close"
- "Skip for now"
- "Maybe later"
- "Accept additional cookies"
- "Yes, I agree"
- "Got it"
- "I Accept"
- "Accept & close"
- "That's OK"
- "ACCEPT ALL"
- "Allow all"
- "OK, I understand"
- "I consent"

Put this EXACT text (as shown in the screenshot, \
preserving case) in the `buttonText` field. This is \
the primary way the button will be found and clicked.

# What to IGNORE (return found=false, certainty=0)

- Confirmation messages ("Your preferences have been saved")
- "Thank you" banners that need no action
- Small notification toasts that auto-dismiss
- Purely informational banners with no actionable buttons
- Banners that have already been dismissed
- Navigation menus, footers, or page chrome

Return ONLY a JSON object matching the required schema."""


# -- Agent class -------------------------------------------------------

class ConsentDetectionAgent(base.BaseAgent):
    """Vision-only agent that detects blocking overlays.

    Sends a screenshot to the LLM and returns overlay type,
    certainty percentage, and button text.  The click module
    handles finding and clicking the element by button text.
    """

    agent_name = config.AGENT_CONSENT_DETECTION
    instructions = _INSTRUCTIONS
    max_tokens = 500
    max_retries = 5
    response_model = _VisionDetectionResponse

    async def detect(
        self,
        screenshot: bytes,
    ) -> consent.CookieConsentDetection:
        """Detect overlays from a screenshot.

        Args:
            screenshot: Raw PNG screenshot bytes.

        Returns:
            A ``CookieConsentDetection`` with button text.
        """
        log.start_timer("vision-detection")
        log.info("Analysing screenshot for overlays...")

        try:
            response = await self._complete_vision(
                user_text=(
                    "Look at this screenshot carefully."
                    " Is there any dialog, banner, overlay,"
                    " or prompt visible that needs to be"
                    " dismissed?\n\n"
                    "If yes, read the EXACT text on the"
                    " button or link to click — do not"
                    " guess, read it from the image.\n\n"
                    "For cookie-consent dialogs, PREFER"
                    " reject/decline/necessary-only buttons"
                    " over accept/allow-all buttons. Only"
                    " choose accept if no reject option"
                    " exists.\n\n"
                    "Rate your certainty from 0 to 100."
                ),
                screenshot=screenshot,
            )
            log.end_timer(
                "vision-detection",
                "Vision analysis complete",
            )

            parsed = self._parse_response(
                response, _VisionDetectionResponse
            )
            if not parsed:
                log.debug(
                    "Structured parse failed, trying text"
                    " fallback"
                )
                parsed = _parse_vision_fallback(response.text)

            return _to_result(parsed)

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
                    "Content filtered by Azure -- vision"
                    " unavailable"
                )
                return consent.CookieConsentDetection.not_found(
                    "Vision unavailable (content filter)"
                )

            log.error(
                "Vision detection failed",
                {"error": msg},
            )
            return consent.CookieConsentDetection.not_found(
                f"Vision failed: {msg}"
            )


# -- Helper functions --------------------------------------------------

def _to_result(
    v: _VisionDetectionResponse,
) -> consent.CookieConsentDetection:
    """Convert a vision response to the domain model."""
    if not v.found:
        log.info(
            "No overlay detected",
            {"reason": v.reason},
        )
        return consent.CookieConsentDetection.not_found(
            v.reason or "No overlay visible"
        )

    if v.certainty < _CERTAINTY_THRESHOLD:
        log.info(
            "Overlay below certainty threshold",
            {
                "certainty": v.certainty,
                "threshold": _CERTAINTY_THRESHOLD,
                "reason": v.reason,
            },
        )
        return consent.CookieConsentDetection.not_found(
            f"Low certainty ({v.certainty}%):"
            f" {v.reason}"
        )

    # Map certainty % to confidence level
    if v.certainty >= 80:
        confidence: consent.ConfidenceLevel = "high"
    elif v.certainty >= 55:
        confidence = "medium"
    else:
        confidence = "low"

    result = consent.CookieConsentDetection(
        found=True,
        overlay_type=v.overlayType,
        selector=None,
        button_text=v.buttonText,
        confidence=confidence,
        reason=v.reason,
    )
    log.info(
        "Detection result",
        {
            "found": True,
            "overlayType": result.overlay_type,
            "buttonText": result.button_text,
            "confidence": result.confidence,
            "certainty": v.certainty,
        },
    )
    return result


def _parse_vision_fallback(
    text: str | None,
) -> _VisionDetectionResponse:
    """Parse raw text when structured output fails."""
    raw = json_parsing.load_json_from_text(text)
    if isinstance(raw, dict):
        return _VisionDetectionResponse(
            found=raw.get("found", False),
            overlayType=raw.get("overlayType"),
            buttonText=raw.get("buttonText"),
            certainty=int(raw.get("certainty", 0)),
            reason=raw.get("reason", ""),
        )
    return _VisionDetectionResponse(
        found=False,
        reason="Failed to parse vision response",
    )
