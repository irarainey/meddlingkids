"""Cookie consent banner detection service.

Delegates to ``ConsentDetectionAgent`` for LLM vision
analysis of screenshots to find overlay dismiss buttons.
"""

from __future__ import annotations

from src import agents
from src.models import consent
from src.utils import logger

log = logger.create_logger("Consent-Detect")


async def detect_cookie_consent(
    screenshot: bytes, html: str
) -> consent.CookieConsentDetection:
    """Detect blocking overlays using LLM vision.

    Args:
        screenshot: Raw PNG screenshot bytes.
        html: Full page HTML.

    Returns:
        Detection result with selector information.
    """
    agent = agents.get_consent_detection_agent()
    if not agent.is_configured:
        log.warn(
            "LLM not configured, skipping consent"
            " detection"
        )
        return consent.CookieConsentDetection.not_found(
            "LLM not configured"
        )

    return await agent.detect(screenshot, html)
