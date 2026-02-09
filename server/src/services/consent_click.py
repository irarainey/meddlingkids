"""
Consent button click strategies.
Prioritizes LLM-suggested selectors, checking main page and iframes.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from playwright.async_api import Frame, Page

from src.services.openai_client import get_deployment_name, get_openai_client
from src.utils.logger import create_logger
from src.utils.retry import with_retry

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
    """Try common close button patterns as a last resort."""
    close_selectors = [
        '[aria-label*="close" i]',
        '[aria-label*="dismiss" i]',
        'button[class*="close"]',
        '[class*="modal-close"]',
    ]
    for sel in close_selectors:
        try:
            log.debug("Trying close button", {"selector": sel})
            await page.locator(sel).first.click(timeout=1000)
            log.success("Close button clicked", {"selector": sel})
            return True
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# Close / Back patterns for closing expanded consent dialogs
# ---------------------------------------------------------------------------
CLOSE_BACK_PATTERNS = [
    re.compile(r"^back\s+to\s+consent$", re.I),
    re.compile(r"^return\s+to\s+consent$", re.I),
    re.compile(r"^go\s+to\s+consent$", re.I),
    re.compile(r"^back$", re.I),
    re.compile(r"^go\s*back$", re.I),
    re.compile(r"^←\s*back$", re.I),
    re.compile(r"^←$", re.I),
    re.compile(r"^return$", re.I),
    re.compile(r"^previous$", re.I),
    re.compile(r"^close$", re.I),
    re.compile(r"^×$", re.I),
    re.compile(r"^x$", re.I),
    re.compile(r"^save\s*(?:&|and)?\s*(?:close|exit)?$", re.I),
    re.compile(r"^save\s+(?:preferences?|settings?|choices?)$", re.I),
    re.compile(r"^confirm\s+(?:preferences?|settings?|choices?)$", re.I),
    re.compile(r"^done$", re.I),
    re.compile(r"^ok$", re.I),
    re.compile(r"^cancel$", re.I),
]


async def close_expanded_dialogs(page: Page, steps_to_close: int) -> bool:
    """
    Close expanded consent dialogs and return to main consent screen.
    Uses pattern matching first, then falls back to LLM assistance if stuck.
    """
    log.info("Attempting to close expanded dialogs...", {"stepsToClose": steps_to_close})

    closed_any = False
    failed_attempts = 0
    max_failed_attempts = 2
    max_total_attempts = steps_to_close + 2

    for attempt in range(1, max_total_attempts + 1):
        log.debug(f"Close attempt {attempt}/{max_total_attempts} (failed: {failed_attempts})...")

        # Strategy 1: Quick pattern-based back/close buttons
        if await _try_click_back_button(page, 500):
            closed_any = True
            failed_attempts = 0
            await page.wait_for_timeout(400)
            continue

        # Strategy 2: Aria-label buttons
        if await _try_aria_close_buttons(page, 500):
            closed_any = True
            failed_attempts = 0
            await page.wait_for_timeout(400)
            continue

        # Strategy 3: Escape key
        log.debug("Trying Escape key...")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)

        failed_attempts += 1

        if failed_attempts >= max_failed_attempts:
            log.info("Pattern matching failed, asking LLM for navigation help...")
            llm_result = await _ask_llm_for_navigation_help(page)
            if llm_result.get("clicked"):
                closed_any = True
                failed_attempts = 0
                await page.wait_for_timeout(500)
                continue
            else:
                log.warn("LLM navigation help failed", {"reason": llm_result.get("reason")})
                break

    if closed_any:
        log.success("Closed expanded dialogs")
    else:
        log.debug("Could not close expanded dialogs")

    return closed_any


async def _ask_llm_for_navigation_help(page: Page) -> dict[str, Any]:
    """Ask LLM to analyze screenshot and help navigate back to main consent."""
    client = get_openai_client()
    if not client:
        return {"clicked": False, "reason": "OpenAI not configured"}

    try:
        screenshot = await page.screenshot(type="png")
        b64 = base64.b64encode(screenshot).decode("utf-8")

        button_texts: list[str] = await page.evaluate(
            """() => {
                const buttons = document.querySelectorAll('button, a, [role="button"]');
                return Array.from(buttons)
                    .map(b => b.innerText?.trim())
                    .filter(t => t && t.length > 0 && t.length < 50)
                    .slice(0, 20);
            }"""
        )

        log.debug("Asking LLM for navigation help", {"visibleButtons": len(button_texts)})

        deployment = get_deployment_name()
        response = await with_retry(
            lambda: client.chat.completions.create(
                model=deployment,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            'You are helping navigate a cookie consent dialog. The user has expanded '
                            'partner/vendor information and needs to get back to the main consent dialog '
                            'where they can click "Accept All" or "I Accept".\n\n'
                            'Analyze the screenshot and identify the button to click to navigate BACK.\n\n'
                            'Respond with JSON only:\n'
                            '{"buttonText": "exact text", "selector": "CSS selector if visible", '
                            '"confidence": "high"|"medium"|"low", "reason": "brief explanation"}\n\n'
                            'If no clear navigation button:\n'
                            '{"buttonText": null, "reason": "Already on main consent"}'
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                            {
                                "type": "text",
                                "text": f"Visible buttons on page: {', '.join(button_texts)}\n\nWhat button should I click to get back to the main consent dialog?",
                            },
                        ],
                    },
                ],
                max_completion_tokens=300,
            ),
            context="LLM navigation help",
            max_retries=1,
        )

        content = response.choices[0].message.content or "{}"
        json_str = content.strip()
        if json_str.startswith("```"):
            json_str = re.sub(r"```json?\n?", "", json_str)
            json_str = re.sub(r"```$", "", json_str).strip()

        result = json.loads(json_str)
        log.info("LLM navigation suggestion", {
            "buttonText": result.get("buttonText"),
            "confidence": result.get("confidence"),
            "reason": result.get("reason"),
        })

        if not result.get("buttonText"):
            return {"clicked": False, "reason": result.get("reason", "No button suggested")}

        clicked = await _try_click_by_text(page, result["buttonText"], result.get("selector"))
        if clicked:
            log.success("LLM-guided click successful", {"buttonText": result["buttonText"]})
            return {"clicked": True, "buttonText": result["buttonText"]}

        return {"clicked": False, "reason": "Could not click suggested button"}
    except Exception as error:
        log.warn("LLM navigation help error", {"error": str(error)})
        return {"clicked": False, "reason": str(error)}


async def _try_click_by_text(page: Page, button_text: str, selector: str | None = None) -> bool:
    """Try to click an element by text or selector."""
    if selector:
        try:
            await page.locator(selector).first.click(timeout=1000)
            return True
        except Exception:
            pass

    for strategy in [
        lambda: page.get_by_text(button_text, exact=True).first.click(timeout=1000),
        lambda: page.get_by_text(button_text, exact=False).first.click(timeout=1000),
        lambda: page.get_by_role("button", name=button_text).first.click(timeout=1000),
    ]:
        try:
            await strategy()
            return True
        except Exception:
            pass
    return False


async def _try_click_back_button(page: Page, timeout: int = 1000) -> bool:
    """Try to click a back/close button using pattern matching."""
    try:
        clickables = await page.locator(
            "button, a, [role='button'], span[onclick], div[onclick]"
        ).all()

        for element in clickables:
            try:
                if not await element.is_visible(timeout=100):
                    continue
                text = await element.text_content(timeout=200)
                if not text:
                    continue
                trimmed = text.strip()
                if len(trimmed) > 50:
                    continue
                for pattern in CLOSE_BACK_PATTERNS:
                    if pattern.search(trimmed):
                        log.debug("Found back/close button", {"text": trimmed})
                        await element.click(timeout=timeout)
                        log.success("Clicked back/close button", {"text": trimmed})
                        return True
            except Exception:
                pass
    except Exception:
        pass
    return False


async def _try_aria_close_buttons(page: Page, timeout: int = 1000) -> bool:
    """Try to click aria-label close buttons."""
    close_selectors = [
        '[aria-label*="close" i]',
        '[aria-label*="back" i]',
        '[aria-label*="dismiss" i]',
        '[aria-label*="return" i]',
        'button[class*="back"]',
        'button[class*="close"]',
        '[class*="back-button"]',
        '[class*="close-button"]',
    ]
    for sel in close_selectors:
        try:
            element = page.locator(sel).first
            if await element.is_visible(timeout=150):
                await element.click(timeout=timeout)
                log.debug("Clicked aria close button", {"selector": sel})
                return True
        except Exception:
            pass
    return False

