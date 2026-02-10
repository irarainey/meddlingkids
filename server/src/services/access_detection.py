"""
Access denial and bot blocking detection utilities.
Checks page content for patterns that indicate bot blocking or access denial.
"""

from __future__ import annotations

from playwright.async_api import Page

from src.types.browser import AccessDenialResult

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
]


async def check_for_access_denied(page: Page) -> AccessDenialResult:
    """
    Check if the current page content indicates access denial or bot blocking.
    """
    try:
        title = await page.title()
        title_lower = title.lower()

        for pattern in BLOCKED_TITLE_PATTERNS:
            if pattern in title_lower:
                return AccessDenialResult(
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
                return AccessDenialResult(
                    denied=True,
                    reason=f'Page content indicates blocking: "{pattern}"',
                )

        return AccessDenialResult(denied=False, reason=None)
    except Exception:
        return AccessDenialResult(denied=False, reason=None)
