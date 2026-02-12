"""
Consent button click strategies.
Prioritizes LLM-suggested selectors, checking main page and consent iframes.
"""

from __future__ import annotations

import re
from urllib import parse

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
        hostname = parse.urlparse(frame.url).hostname or ""
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
) -> async_api.Frame | None:
    """Check whether the LLM-detected element actually exists in the DOM.

    Searches the main frame first, then falls back to consent-manager
    iframes.  Returns the frame where the element was found, or
    ``None`` if not found anywhere.
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
                        log.debug("Element found via CSS selector", {"selector": css_selector, "frame": frame.url})
                        return frame
                except Exception:
                    pass
            if text_from_selector:
                try:
                    if await frame.get_by_text(
                        text_from_selector, exact=False
                    ).count() > 0:
                        log.debug("Element found via selector text", {"text": text_from_selector, "frame": frame.url})
                        return frame
                except Exception:
                    pass

        if button_text:
            try:
                if await frame.get_by_role(
                    "button", name=button_text
                ).count() > 0:
                    log.debug("Element found via button role", {"buttonText": button_text, "frame": frame.url})
                    return frame
            except Exception:
                pass
            try:
                if await frame.get_by_text(
                    button_text, exact=False
                ).count() > 0:
                    log.debug("Element found via text search", {"buttonText": button_text, "frame": frame.url})
                    return frame
            except Exception:
                pass

    log.debug("Element not found in any frame", {"selector": selector, "buttonText": button_text})
    return None


async def try_click_consent_button(
    page: async_api.Page,
    selector: str | None,
    button_text: str | None,
    *,
    found_in_frame: async_api.Frame | None = None,
) -> bool:
    """Click the consent/overlay dismiss button identified by the LLM.

    Strategy order
    ~~~~~~~~~~~~~~
    1. If ``found_in_frame`` is provided (from validation), try that
       frame first — this avoids wasting time on frames where the
       element doesn't exist.
    2. LLM-provided selector/text on the **main frame**.
    3. LLM-provided selector/text on **consent-manager iframes**.
    4. Generic close-button heuristics on the **main frame only**.

    Consent iframes are checked *before* generic heuristics so we
    don't waste time scanning hundreds of unrelated links in
    content iframes.

    After every successful click the URL is checked; if it changed
    the browser navigates back and the click is treated as failed.
    """
    log.info("Attempting click", {"selector": selector, "buttonText": button_text})
    original_url = page.url

    # Phase 0: Try the frame where validation already found the element
    if found_in_frame and found_in_frame != page.main_frame:
        log.debug("Trying validated frame first", {"url": found_in_frame.url[:80]})
        if await _try_click_in_frame(found_in_frame, selector, button_text, 3000):
            if await _did_navigate_away(page, original_url):
                return False
            log.success("Click succeeded in validated frame", {"url": found_in_frame.url[:50]})
            return True

    # Phase 1: LLM suggestion on main page
    if await _try_click_in_frame(page.main_frame, selector, button_text, 3000):
        if await _did_navigate_away(page, original_url):
            return False
        log.success("Click succeeded on main page")
        return True

    # Phase 2: LLM suggestion on consent-manager iframes
    consent_frames = [f for f in page.frames if _is_consent_frame(f, page.main_frame)]
    if consent_frames:
        log.debug("Trying consent iframes", {"count": len(consent_frames)})
        for frame in consent_frames:
            frame_url = frame.url
            log.debug("Checking consent iframe", {"url": frame_url[:80]})
            if await _try_click_in_frame(frame, selector, button_text, 3000):
                if await _did_navigate_away(page, original_url):
                    return False
                log.success("Click succeeded in consent iframe", {"url": frame_url[:50]})
                return True

    # Phase 3: Generic close-button heuristics (main frame only)
    log.debug("Trying generic close buttons on main frame...")
    if await _try_close_buttons(page.main_frame):
        if await _did_navigate_away(page, original_url):
            return False
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


# ── Href patterns that are safe (do NOT navigate away) ──────────────
_SAFE_HREF_RE = re.compile(
    r"^(?:"
    r"javascript:\s*(?:void\s*\(?\s*0?\s*\)?)?"
    r"|#.*"
    r")$",
    re.IGNORECASE,
)


async def _is_safe_to_click(
    locator: async_api.Locator, timeout: int = 2000
) -> bool | None:
    """Return whether clicking this element will navigate away.

    Returns:
        ``True`` — element is safe to click (button, JS-driven, etc.).
        ``False`` — element has a real ``href`` and would navigate.
        ``None`` — could not determine (timeout, cross-origin, detached).

    An element is considered safe when:
    * it is a ``<button>`` (buttons don't navigate by default),
    * its ``href`` is ``#``, ``javascript:void(0)``, or similar,
    * it has an inline ``onclick`` handler (JS-driven action), or
    * it has no ``href`` at all (e.g. a ``<div>`` wired up via JS).

    An ``<a>`` with a real URL in ``href`` is **not** safe because
    clicking it would leave the current page.

    The *timeout* (ms) caps how long we wait for the element to
    become available for evaluation.  Cross-origin or deeply
    nested iframes can stall for the full Playwright default
    (30 s), so a short timeout avoids blocking the pipeline.
    """
    try:
        return await locator.evaluate(
            """
            el => {
                const tag = el.tagName.toLowerCase();

                // <button> elements don't navigate.
                if (tag === 'button' || el.type === 'submit' || el.type === 'button') {
                    return true;
                }

                // Inline onclick handler → JS-driven action.
                if (el.hasAttribute('onclick')) {
                    return true;
                }

                // role="button" without an href is JS-driven.
                if (el.getAttribute('role') === 'button' && !el.hasAttribute('href')) {
                    return true;
                }

                // Elements without an href (span, div, etc.) are fine.
                const href = el.getAttribute('href');
                if (href === null || href === undefined) {
                    return true;
                }

                // Safe href values: "#", "#foo", "javascript:void(0)", etc.
                const trimmed = href.trim();
                if (
                    trimmed === '' ||
                    trimmed.startsWith('#') ||
                    /^javascript:\s*(void\s*\(?\s*0?\s*\)?)?\s*;?\s*$/i.test(trimmed)
                ) {
                    return true;
                }

                // Any other href would navigate — not safe.
                return false;
            }
            """,
            timeout=timeout,
        )
    except Exception:
        # Timeout, element detached, cross-origin iframe, etc.
        # Return None so the caller can decide policy.
        log.debug("Could not evaluate element safety (timeout/error)")
        return None


async def _safe_click(
    locator: async_api.Locator,
    timeout: int,
    *,
    force_on_timeout: bool = False,
) -> bool:
    """Click a locator, checking navigation safety first.

    Args:
        locator: Playwright locator for the target element.
        timeout: Click timeout in ms.
        force_on_timeout: When ``True``, proceed with the
            click even when safety evaluation times out
            (``_is_safe_to_click`` returns ``None``).
            Use for LLM-identified elements where we have
            high confidence the element is a consent button.
    """
    try:
        first = locator.first
        safety = await _is_safe_to_click(first)

        if safety is False:
            # Definitively would navigate — skip
            log.debug(
                "Skipping click — element would navigate away",
                {"locator": str(locator)},
            )
            return False

        if safety is None and not force_on_timeout:
            # Timeout/error and caller doesn't want to force
            log.debug(
                "Skipping click — safety unknown (timeout)",
                {"locator": str(locator)},
            )
            return False

        if safety is None:
            log.debug(
                "Safety evaluation timed out — clicking"
                " anyway (LLM-identified element)",
                {"locator": str(locator)},
            )

        await first.click(timeout=timeout)
        return True
    except Exception:
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
    """Try clicking in a specific frame using LLM-provided selector and text.

    Every candidate element is checked with ``_safe_click`` before it
    is clicked.  Uses ``force_on_timeout=True`` because these are
    LLM-identified consent elements — if the safety check times out
    on a busy page, we still try clicking since the LLM identified
    the element as a consent button.
    """
    # Strategy 1: CSS selector (strip non-standard pseudo-selectors)
    if selector:
        css_selector, text_from_selector = _parse_selector(selector)

        if css_selector:
            if await _safe_click(
                frame.locator(css_selector), timeout,
                force_on_timeout=True,
            ):
                return True

        # If the LLM gave :has-text() / :contains(), use the inner
        # text with Playwright's role and text locators.
        if text_from_selector:
            for locator in [
                frame.get_by_role("button", name=text_from_selector),
                frame.get_by_text(text_from_selector, exact=False),
            ]:
                if await _safe_click(
                    locator, timeout, force_on_timeout=True,
                ):
                    return True

    # Strategy 2: Button/link/text with buttonText
    if button_text:
        for locator in [
            frame.get_by_role("button", name=button_text),
            frame.get_by_role("link", name=button_text),
            frame.get_by_text(button_text, exact=True),
            frame.get_by_text(button_text, exact=False),
        ]:
            if await _safe_click(
                locator, timeout, force_on_timeout=True,
            ):
                return True

    return False


async def _try_close_buttons(frame: async_api.Frame) -> bool:
    """Try common close button patterns as a last resort.

    Searches **only** within the given frame (typically the main
    frame).  Using ``page``-level locators would search every
    iframe on the page, matching unrelated links in content
    iframes and stalling on cross-origin evaluate calls.

    Uses ``force_on_timeout=False`` because generic heuristics
    can match non-consent elements (page links with "accept" in
    their aria-label, etc.).  If safety can't be evaluated, it's
    better to skip than risk navigating away.

    Prefers role-based locators (``get_by_role``) for accessibility,
    then falls back to CSS attribute/class selectors.
    """
    # Role-based strategies — try common accept/dismiss button text
    role_patterns: list[tuple[str, async_api.Locator]] = [
        (
            "button[name~=accept]",
            frame.get_by_role("button", name=re.compile(
                r"accept|agree|allow|got it|i understand|okay|ok\b|continue|confirm",
                re.IGNORECASE,
            )),
        ),
        (
            "button[name~=dismiss]",
            frame.get_by_role("button", name=re.compile(
                r"close|dismiss|skip|no thanks|not now|maybe later|later|reject|decline|deny",
                re.IGNORECASE,
            )),
        ),
    ]
    for label, locator in role_patterns:
        log.debug("Trying close button", {"selector": label})
        if await _safe_click(locator, 400, force_on_timeout=False):
            log.success("Close button clicked", {"selector": label})
            return True

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
        log.debug("Trying close button", {"selector": sel})
        if await _safe_click(frame.locator(sel), 400, force_on_timeout=False):
            log.success("Close button clicked", {"selector": sel})
            return True
    return False

