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
from src.agents.prompts import consent_detection
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


# -- Agent class -------------------------------------------------------


class ConsentDetectionAgent(base.BaseAgent):
    """Vision-only agent that detects blocking overlays.

    Sends a screenshot to the LLM and returns overlay type,
    certainty percentage, and button text.  The click module
    handles finding and clicking the element by button text.
    """

    agent_name = config.AGENT_CONSENT_DETECTION
    instructions = consent_detection.INSTRUCTIONS
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
                    "For cookie-consent dialogs, ALWAYS"
                    " choose the ACCEPT ALL / ALLOW ALL"
                    " button. Never choose reject, decline,"
                    " or necessary-only options.\n\n"
                    "Rate your certainty from 0 to 100."
                ),
                screenshot=screenshot,
            )
            log.end_timer(
                "vision-detection",
                "Vision analysis complete",
            )

            parsed = self._parse_response(response, _VisionDetectionResponse)
            if not parsed:
                log.debug("Structured parse failed, trying text fallback")
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
                log.warn("Content filtered by Azure -- vision unavailable")
                return consent.CookieConsentDetection.not_found("Vision unavailable (content filter)")

            log.error(
                "Vision detection failed",
                {"error": msg},
            )
            return consent.CookieConsentDetection.not_found(f"Vision failed: {msg}")


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
        return consent.CookieConsentDetection.not_found(v.reason or "No overlay visible")

    if v.certainty < _CERTAINTY_THRESHOLD:
        log.info(
            "Overlay below certainty threshold",
            {
                "certainty": v.certainty,
                "threshold": _CERTAINTY_THRESHOLD,
                "reason": v.reason,
            },
        )
        return consent.CookieConsentDetection.not_found(f"Low certainty ({v.certainty}%): {v.reason}")

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
