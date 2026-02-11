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

# Substrings in the hostname that indicate an ad-tech sync/pixel
# iframe rather than a real consent-manager frame.
_CONSENT_HOST_EXCLUDE = (
    "cookie-sync", "pixel", "-sync.", "ad-sync",
    "user-sync", "match.", "prebid",
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
    if any(ex in hostname_lower for ex in _CONSENT_HOST_EXCLUDE):
        return False
    return any(kw in hostname_lower for kw in _CONSENT_HOST_KEYWORDS)


async def validate_element_exists(
    page: async_api.Page,
    selector: str | None,
    button_text: str | None,
) -> bool:
    """Check whether the LLM-detected element actually exists in the DOM.

    Searches the main frame first, then falls back to consent-manager
    iframes.  Returns ``True`` if found anywhere.
    """
    frames = [page.main_frame] + [
        f for f in page.frames
        if _is_consent_frame(f, page.main_frame)
    ]

    for frame in frames:
        if selector:
            css_selector, text_from_selector = _parse_selector(selector)
            if css_selector:
                try:
                    if await frame.locator(css_selector).count() > 0:
                        return True
                except Exception:
                    pass
            if text_from_selector:
                try:
                    if await frame.get_by_text(
                        text_from_selector, exact=False
                    ).count() > 0:
                        return True
                except Exception:
                    pass

        if button_text:
            try:
                if await frame.get_by_role(
                    "button", name=button_text
                ).count() > 0:
                    return True
            except Exception:
                pass
            try:
                if await frame.get_by_text(
                    button_text, exact=False
                ).count() > 0:
                    return True
            except Exception:
                pass

    return False


async def try_click_consent_button(
    page: async_api.Page,
    selector: str | None,
    button_text: str | None,
) -> bool:
    """
    Click a consent/dismiss button using LLM-provided selector and text.
    Tries the main page first — consent dialogs, paywalls, and sign-in
    prompts are almost always rendered in the top-level document.
    Iframes are only checked as a last resort.

    After every click, checks whether the page navigated to a different
    URL.  Consent dismiss buttons almost never navigate — if the URL
    changed, the click hit a real link and we go back.
    """
    log.info("Attempting click", {"selector": selector, "buttonText": button_text})
    original_url = page.url

    # Phase 1: Try main page (where overlays almost always live)
    if await _try_click_in_frame(page.main_frame, selector, button_text, 1500):
        if await _did_navigate_away(page, original_url):
            return False
        log.success("Click succeeded on main page")
        return True

    # Phase 2: Generic close buttons on main page
    log.debug("Trying generic close buttons...")
    if await _try_close_buttons(page):
        if await _did_navigate_away(page, original_url):
            return False
        return True

    # Phase 3: Last resort — try consent-manager iframes
    consent_frames = [f for f in page.frames if _is_consent_frame(f, page.main_frame)]
    if consent_frames:
        log.debug("Trying consent iframes as last resort", {"count": len(consent_frames)})
        for frame in consent_frames:
            frame_url = frame.url
            log.debug("Checking consent iframe", {"url": frame_url[:80]})
            if await _try_click_in_frame(frame, selector, button_text, 1500):
                if await _did_navigate_away(page, original_url):
                    return False
                log.success("Click succeeded in consent iframe", {"url": frame_url[:50]})
                return True

    log.warn("All click strategies failed")
    return False


async def _did_navigate_away(page: async_api.Page, original_url: str) -> bool:
    """Check if clicking caused a page navigation and go back if so.

    Consent dismiss buttons virtually never navigate — they use
    ``javascript:void(0)``, ``href="#"``, or JS event handlers.
    If the URL changed, we almost certainly clicked a real link.
    """
    try:
        await page.wait_for_timeout(300)
        current_url = page.url
        if current_url != original_url:
            log.warn(
                "Click caused navigation — likely a real link, going back",
                {"from": original_url[:80], "to": current_url[:80]},
            )
            await page.go_back(wait_until="domcontentloaded", timeout=5000)
            return True
    except Exception as e:
        log.warn("Navigation check failed", {"error": str(e)})
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
    # Role-based strategies — try common accept/dismiss button text
    role_patterns: list[tuple[str, async_api.Locator]] = [
        (
            "button[name~=accept]",
            page.get_by_role("button", name=re.compile(
                r"accept|agree|allow|got it|i understand|okay|ok\b|continue|confirm",
                re.IGNORECASE,
            )),
        ),
        (
            "button[name~=dismiss]",
            page.get_by_role("button", name=re.compile(
                r"close|dismiss|skip|no thanks|not now|maybe later|later|reject|decline|deny",
                re.IGNORECASE,
            )),
        ),
    ]
    for label, locator in role_patterns:
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
        '[aria-label*="accept" i]',
        '[aria-label*="agree" i]',
        'button[class*="close"]',
        'button[class*="accept"]',
        'button[class*="agree"]',
        'button[class*="consent"]',
        '[class*="modal-close"]',
        '[class*="banner-close"]',
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

