"""Consent details extraction service.

Delegates to ``ConsentExtractionAgent`` for vision-based
extraction of cookie categories, partners, and purposes
from consent dialogs.
"""

from __future__ import annotations

from playwright import async_api

from src import agents
from src.models import consent
from src.utils import logger

log = logger.create_logger("Consent-Extract")


async def extract_consent_details(
    page: async_api.Page, screenshot: bytes
) -> consent.ConsentDetails:
    """Extract detailed consent information from a page.

    Args:
        page: Playwright page for DOM text extraction.
        screenshot: Raw PNG screenshot bytes.

    Returns:
        Structured ``ConsentDetails``.
    """
    agent = agents.get_consent_extraction_agent()
    if not agent.is_configured:
        log.warn(
            "LLM not configured, skipping consent"
            " extraction"
        )
        return consent.ConsentDetails.empty()

    return await agent.extract(page, screenshot)
