"""
Consent button click strategies.
Prioritizes LLM-suggested selectors, checking main page and consent iframes.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from playwright import async_api

from src.utils import logger

log = logger.create_logger("Consent-Click")

# Consent-manager keywords matched against iframe **hostname** only.
# Matching the full URL would false-positive on ad-sync iframes that
# carry ``gdpr=1`` or ``gdpr_consent=…`` in their query strings.
_CONSENT_HOST_KEYWORDS = (
    "consent", "onetrust", "cookiebot", "sourcepoint",
    "trustarc", "didomi", "quantcast", "gdpr", "privacy",
    "cmp", "cookie",
)


def _is_consent_frame(frame: async_api.Frame, main_frame: async_api.Frame) -> bool:
    """Return True if the frame looks like a consent-manager iframe."""
    if frame == main_frame:
        return False
    try:
        hostname = urlparse(frame.url).hostname or ""
    except Exception:
        return False
    hostname_lower = hostname.lower()
    return any(kw in hostname_lower for kw in _CONSENT_HOST_KEYWORDS)


async def try_click_consent_button(
    page: async_api.Page,
    selector: str | None,
    button_text: str | None,
) -> bool:
    """
    Click a consent/dismiss button using LLM-provided selector and text.
    Only searches consent-manager iframes (identified by hostname) and
    the main page — never ad or tracking iframes.
    """
    log.info("Attempting click", {"selector": selector, "buttonText": button_text})

    # Phase 1: Try consent-manager iframes first
    consent_frames = [f for f in page.frames if _is_consent_frame(f, page.main_frame)]
    if consent_frames:
        log.debug("Found consent iframes", {"count": len(consent_frames)})

    for frame in consent_frames:
        frame_url = frame.url
        log.debug("Checking consent iframe", {"url": frame_url[:80]})
        if await _try_click_in_frame(frame, selector, button_text, 1500):
            log.success("Click succeeded in consent iframe", {"url": frame_url[:50]})
            return True

    # Phase 2: Try main page
    if await _try_click_in_frame(page.main_frame, selector, button_text, 1500):
        log.success("Click succeeded on main page")
        return True

    # Phase 3: Last resort - generic close buttons on main page
    log.debug("Trying generic close buttons...")
    if await _try_close_buttons(page):
        return True

    log.warn("All click strategies failed")
    return False


# Regex patterns for non-standard pseudo-selectors the LLM
# sometimes produces.  We extract the inner text so we can
# fall back to Playwright role/text matching.
_PSEUDO_TEXT_RE = re.compile(
    r':(?:has-text|contains)\(["\'](.+?)["\']\)',
)


def _parse_selector(selector: str) -> tuple[str | None, str | None]:
    """Split an LLM selector into a pure CSS part and extracted text.

    If the selector contains ``:has-text(...)`` or ``:contains(...)``,
    strip the pseudo-selector to get a valid CSS prefix (if any) and
    return the inner text separately for role/text matching.

    Returns:
        (css_selector_or_None, extracted_text_or_None)
    """
    m = _PSEUDO_TEXT_RE.search(selector)
    if not m:
        return selector, None
    # e.g. "button:has-text('Accept')" → css_part="button", text="Accept"
    css_part = selector[: m.start()].strip() or None
    return css_part, m.group(1)


async def _try_click_in_frame(
    frame: async_api.Frame,
    selector: str | None,
    button_text: str | None,
    timeout: int,
) -> bool:
    """Try clicking in a specific frame using LLM-provided selector and text."""
    # Strategy 1: CSS selector (strip non-standard pseudo-selectors)
    if selector:
        css_selector, text_from_selector = _parse_selector(selector)

        if css_selector:
            try:
                await frame.locator(css_selector).first.click(timeout=timeout)
                return True
            except Exception:
                pass

        # If the LLM gave :has-text() / :contains(), use the inner
        # text with Playwright's role and text locators.
        if text_from_selector:
            for strategy in [
                lambda: frame.get_by_role("button", name=text_from_selector).first.click(timeout=timeout),
                lambda: frame.get_by_text(text_from_selector, exact=False).first.click(timeout=timeout),
            ]:
                try:
                    await strategy()
                    return True
                except Exception:
                    pass

    # Strategy 2: Button/link/text with buttonText
    if button_text:
        for strategy in [
            lambda: frame.get_by_role("button", name=button_text).first.click(timeout=timeout),
            lambda: frame.get_by_role("link", name=button_text).first.click(timeout=timeout),
            lambda: frame.get_by_text(button_text, exact=True).first.click(timeout=timeout),
            lambda: frame.get_by_text(button_text, exact=False).first.click(timeout=timeout),
        ]:
            try:
                await strategy()
                return True
            except Exception:
                pass

    return False


async def _try_close_buttons(page: async_api.Page) -> bool:
    """Try common close button patterns as a last resort.

    Prefers role-based locators (``get_by_role``) for accessibility,
    then falls back to CSS attribute/class selectors.
    """
    # Role-based strategies first (preferred by Playwright guidelines)
    role_strategies: list[tuple[str, async_api.Locator]] = [
        (
            "button[name~=close]",
            page.get_by_role("button", name=re.compile(
                r"close|dismiss", re.IGNORECASE
            )),
        ),
    ]
    for label, locator in role_strategies:
        try:
            log.debug("Trying close button", {"selector": label})
            await locator.first.click(timeout=1000)
            log.success("Close button clicked", {"selector": label})
            return True
        except Exception:
            pass

    # CSS fallback selectors
    css_selectors = [
        '[aria-label*="close" i]',
        '[aria-label*="dismiss" i]',
        'button[class*="close"]',
        '[class*="modal-close"]',
    ]
    for sel in css_selectors:
        try:
            log.debug("Trying close button", {"selector": sel})
            await page.locator(sel).first.click(timeout=1000)
            log.success("Close button clicked", {"selector": sel})
            return True
        except Exception:
            pass
    return False

