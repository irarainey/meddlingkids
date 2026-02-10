"""
Consent button click strategies.
Prioritizes LLM-suggested selectors, checking main page and iframes.
"""

from __future__ import annotations

import re

from playwright.async_api import Frame, Page

from src.utils.logger import create_logger

log = create_logger("Consent-Click")


async def try_click_consent_button(
    page: Page,
    selector: str | None,
    button_text: str | None,
) -> bool:
    """
    Click a consent/dismiss button using LLM-provided selector and text.
    Checks iframes FIRST since consent managers often use iframes.
    """
    log.info("Attempting click", {"selector": selector, "buttonText": button_text})

    # Phase 1: Try iframes FIRST (consent managers often use iframes)
    frames = page.frames
    consent_keywords = (
        "consent", "onetrust", "cookiebot", "sourcepoint",
        "trustarc", "didomi", "quantcast", "gdpr", "privacy",
    )
    consent_frames = [
        f for f in frames
        if f != page.main_frame
        and any(kw in f.url.lower() for kw in consent_keywords)
    ]

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

    # Phase 3: Try remaining iframes
    other_frames = [
        f for f in frames
        if f != page.main_frame and f not in consent_frames
    ]
    if other_frames:
        log.debug("Checking remaining iframes", {"count": len(other_frames)})
        for frame in other_frames:
            if await _try_click_in_frame(frame, selector, button_text, 1500):
                log.success("Click succeeded in iframe", {"url": frame.url[:50]})
                return True

    # Phase 4: Last resort - generic close buttons
    log.debug("Trying generic close buttons...")
    if await _try_close_buttons(page):
        return True

    log.warn("All click strategies failed")
    return False


async def _try_click_in_frame(
    frame: Frame,
    selector: str | None,
    button_text: str | None,
    timeout: int,
) -> bool:
    """Try clicking in a specific frame using LLM-provided selector and text."""
    # Strategy 1: Direct CSS selector
    if selector:
        contains_match = re.search(r':contains\(["\'](.+?)["\']\)', selector)
        actual_selector = None if contains_match else selector
        text_from_selector = contains_match.group(1) if contains_match else None

        if actual_selector:
            try:
                await frame.locator(actual_selector).first.click(timeout=timeout)
                return True
            except Exception:
                pass

        if text_from_selector:
            try:
                await frame.get_by_text(text_from_selector, exact=False).first.click(timeout=timeout)
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


async def _try_close_buttons(page: Page) -> bool:
    """Try common close button patterns as a last resort.

    Prefers role-based locators (``get_by_role``) for accessibility,
    then falls back to CSS attribute/class selectors.
    """
    # Role-based strategies first (preferred by Playwright guidelines)
    role_strategies: list[tuple[str, object]] = [
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

