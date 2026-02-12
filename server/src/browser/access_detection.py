"""
Access denial and bot blocking detection utilities.
Checks page content for patterns that indicate bot blocking or access denial.
"""

from __future__ import annotations

from playwright import async_api

from src.models import browser
from src.utils import logger

log = logger.create_logger("AccessDetection")

# ============================================================================
# Detection Patterns
# ============================================================================

BLOCKED_TITLE_PATTERNS = [
    "access denied",
    "forbidden",
    "403",
    "401",
    "blocked",
    "not allowed",
    "cloudflare",
    "security check",
    "captcha",
    "robot",
    "bot detection",
    "please verify",
    "are you human",
    "just a moment",
    "checking your browser",
    "ddos protection",
    "attention required",
]

BLOCKED_BODY_PATTERNS = [
    "access denied",
    "access to this page has been denied",
    "you have been blocked",
    "this request was blocked",
    "automated access",
    "bot traffic",
    "enable javascript and cookies",
    "please complete the security check",
    "checking if the site connection is secure",
    "verify you are human",
    "we have detected unusual activity",
    "your ip has been blocked",
    "rate limit exceeded",
    # Tollbit CDN-level bot paywall (used by telegraph.co.uk etc.)
    "tollbit token",
    "valid tollbit",
    "cannot be accessed without",
]


async def check_for_access_denied(page: async_api.Page) -> browser.AccessDenialResult:
    """
    Check if the current page content indicates access denial or bot blocking.
    """
    try:
        title = await page.title()
        title_lower = title.lower()

        for pattern in BLOCKED_TITLE_PATTERNS:
            if pattern in title_lower:
                log.warn("Access denied detected via title", {"title": title, "pattern": pattern})
                return browser.AccessDenialResult(
                    denied=True,
                    reason=f'Page title indicates blocking: "{title}"',
                )

        body_text = await page.evaluate(
            """() => {
                const body = document.body;
                return body ? body.innerText.substring(0, 2000).toLowerCase() : '';
            }"""
        )

        for pattern in BLOCKED_BODY_PATTERNS:
            if pattern in body_text:
                log.warn("Access denied detected via body content", {"pattern": pattern})
                return browser.AccessDenialResult(
                    denied=True,
                    reason=f'Page content indicates blocking: "{pattern}"',
                )

        log.debug("No access denial detected")
        return browser.AccessDenialResult(denied=False, reason=None)
    except Exception as exc:
        log.debug(f"Access check error (assuming no denial): {exc}")
        return browser.AccessDenialResult(denied=False, reason=None)
