"""
Consent dialog expansion — navigate partner/vendor lists and load-more buttons.

Expands consent dialogs to reveal partner and vendor information
for privacy analysis, without modifying consent state.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from playwright.async_api import Frame, Page

from src.utils.logger import create_logger

log = create_logger("Consent-Expansion")


# ---------------------------------------------------------------------------
# Expansion patterns
# ---------------------------------------------------------------------------

MANAGE_OPTIONS_PATTERNS = [
    re.compile(r"^manage\s+(?:cookie\s+)?(?:preferences?|options?|settings?)$", re.I),
    re.compile(r"^cookie\s+settings?$", re.I),
    re.compile(r"^privacy\s+settings?$", re.I),
    re.compile(r"^customise?\s+(?:cookies?)?$", re.I),
    re.compile(r"^more\s+options?$", re.I),
    re.compile(r"^advanced\s+settings?$", re.I),
    re.compile(r"^options?$", re.I),
]

PARTNER_LIST_BUTTON_PATTERNS = [
    re.compile(r"^partners?$", re.I),
    re.compile(r"^view\s+(?:all\s+)?(?:our\s+)?partners?$", re.I),
    re.compile(r"^show\s+(?:all\s+)?partners?$", re.I),
    re.compile(r"^(?:see\s+)?(?:our\s+)?(?:\d+\s+)?partners?$", re.I),
    re.compile(r"partners?\s*\([\d,]+\)", re.I),
    re.compile(r"^vendor\s*list$", re.I),
    re.compile(r"^vendors?$", re.I),
    re.compile(r"^view\s+(?:all\s+)?vendors?$", re.I),
    re.compile(r"^(?:our\s+)?vendors?\s*\([\d,]+\)$", re.I),
    re.compile(r"^iab\s+vendors?", re.I),
    re.compile(r"^(?:tcf\s+)?vendor\s+list$", re.I),
    re.compile(r"^(?:view\s+)?third[- ]part(?:y|ies)", re.I),
    re.compile(r"^see\s+all$", re.I),
    re.compile(r"^view\s+all$", re.I),
    re.compile(r"^show\s+all$", re.I),
    re.compile(r"^more\s+info(?:rmation)?$", re.I),
    re.compile(r"^learn\s+more$", re.I),
]

LEGITIMATE_INTEREST_PATTERNS = [
    re.compile(r"^legitimate\s+interest$", re.I),
    re.compile(r"^legitimate\s+interests?$", re.I),
    re.compile(r"^view\s+legitimate\s+interest", re.I),
    re.compile(r"^legit(?:imate)?\s+int(?:erest)?", re.I),
]


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

ExpansionStep = dict[str, str]
ExpansionStepCallback = Callable[[ExpansionStep], Any]


@dataclass
class ExpansionResult:
    """Result of expanding the consent dialog."""

    expanded: bool = False
    steps: list[ExpansionStep] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def expand_partner_list(
    page: Page,
    on_step: ExpansionStepCallback | None = None,
) -> ExpansionResult:
    """
    Expand consent dialog to reveal partner/vendor information.
    Informational only — gathers data about partners before accepting.
    """
    log.info("Starting partner info expansion (informational only)...")
    result = ExpansionResult()

    expansion_timeout = 10000  # 10 seconds max
    start_time = time.monotonic()

    def is_timed_out() -> bool:
        return (time.monotonic() - start_time) * 1000 > expansion_timeout

    def elapsed() -> int:
        return int((time.monotonic() - start_time) * 1000)

    def get_frames_to_check() -> list[Frame]:
        frames = page.frames
        consent_kw = (
            "consent", "onetrust", "cookiebot", "sourcepoint",
            "trustarc", "didomi", "quantcast", "gdpr", "privacy",
            "cmp", "inmobi",
        )
        consent_frames = [
            f for f in frames
            if f != page.main_frame
            and any(kw in f.url.lower() for kw in consent_kw)
        ]
        log.debug(
            "Frames to check",
            {"main": 1, "consentIframes": len(consent_frames), "totalFrames": len(frames)},
        )
        return [page.main_frame, *consent_frames]

    try:
        # Step 1: "More Options" / "Manage Options"
        log.info("Step 1: Looking for manage options button...", {"elapsed": elapsed()})
        if not is_timed_out():
            for frame in get_frames_to_check():
                clicked = await _try_click_expansion_button(frame, MANAGE_OPTIONS_PATTERNS, 2000)
                if clicked["success"]:
                    log.success("Clicked manage options button", {"text": clicked["buttonText"], "elapsed": elapsed()})
                    result.expanded = True
                    step: ExpansionStep = {"type": "manage-options", "buttonText": clicked["buttonText"]}
                    result.steps.append(step)
                    await _wait_for_dom_update(page, 1500)
                    if on_step:
                        await on_step(step)
                    break

        # Step 2: "Partners" button
        log.info("Step 2: Looking for partners button...", {"elapsed": elapsed()})
        if not is_timed_out():
            for frame in get_frames_to_check():
                clicked = await _try_click_expansion_button(frame, PARTNER_LIST_BUTTON_PATTERNS, 2000)
                if clicked["success"]:
                    log.success("Clicked partner list button", {"text": clicked["buttonText"], "elapsed": elapsed()})
                    result.expanded = True
                    step = {"type": "partners", "buttonText": clicked["buttonText"]}
                    result.steps.append(step)
                    await _wait_for_dom_update(page, 1500)
                    if on_step:
                        await on_step(step)
                    break

        # Step 3: "Legitimate Interest"
        log.info("Step 3: Looking for legitimate interest button...", {"elapsed": elapsed()})
        if not is_timed_out():
            for frame in get_frames_to_check():
                clicked = await _try_click_expansion_button(frame, LEGITIMATE_INTEREST_PATTERNS, 2000)
                if clicked["success"]:
                    log.success("Clicked legitimate interest button", {"text": clicked["buttonText"], "elapsed": elapsed()})
                    result.expanded = True
                    step = {"type": "legitimate-interest", "buttonText": clicked["buttonText"]}
                    result.steps.append(step)
                    await _wait_for_dom_update(page, 1000)
                    if on_step:
                        await on_step(step)
                    break

        # Step 4: "Load more" buttons
        log.info("Step 4: Looking for load more buttons...", {"elapsed": elapsed()})
        if not is_timed_out():
            if await _try_expand_scrollable_lists(page):
                log.success("Clicked load more button", {"elapsed": elapsed()})
                step = {"type": "load-more", "buttonText": "Load more"}
                result.steps.append(step)
                if on_step:
                    await on_step(step)

    except Exception as error:
        log.warn("Expansion process error", {"error": str(error), "elapsed": elapsed()})

    if is_timed_out():
        log.warn("Partner expansion timed out", {"elapsed": elapsed(), "timeout": expansion_timeout})

    if result.expanded:
        log.success(
            "Partner info expansion complete",
            {"steps": len(result.steps), "types": ", ".join(s["type"] for s in result.steps), "elapsed": elapsed()},
        )
    else:
        log.info("No partner expansion buttons found", {"elapsed": elapsed()})

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _wait_for_dom_update(page: Page, max_wait: int) -> None:
    """Wait for DOM to update after a click action."""
    start = time.monotonic()
    log.debug("Waiting for DOM update...", {"maxWait": max_wait})
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=max_wait)
    except Exception:
        pass

    elapsed_ms = (time.monotonic() - start) * 1000
    if elapsed_ms < 500:
        await page.wait_for_timeout(int(500 - elapsed_ms))

    log.debug("DOM update wait complete", {"actualWait": int((time.monotonic() - start) * 1000)})


async def _try_click_expansion_button(
    frame: Frame,
    patterns: list[re.Pattern[str]],
    timeout: int,
) -> dict[str, Any]:
    """Try clicking a button matching one of the patterns."""
    page = frame.page

    try:
        clickables = await frame.locator(
            "button, a, [role='button'], [onclick], [class*='link'], span[tabindex], div[tabindex], [class*='tab'], [class*='accordion']"
        ).all()

        log.debug("Found clickable elements", {"count": len(clickables)})

        for element in clickables:
            try:
                if not await element.is_visible(timeout=200):
                    continue
                text = await element.text_content(timeout=500)
                if not text:
                    continue
                trimmed = text.strip()
                if len(trimmed) > 100:
                    continue

                for pattern in patterns:
                    if pattern.search(trimmed):
                        tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
                        log.info("Found matching expansion element", {"text": trimmed[:50], "tag": tag_name})

                        href = await element.get_attribute("href") if tag_name == "a" else None
                        might_navigate = href and not href.startswith("#") and not href.startswith("javascript:")

                        if might_navigate:
                            url_before = page.url
                            await element.click(timeout=timeout)
                            await page.wait_for_timeout(500)
                            url_after = page.url
                            if url_after != url_before:
                                log.warn("Link caused page navigation, going back")
                                try:
                                    await page.go_back(timeout=3000)
                                except Exception:
                                    pass
                                await page.wait_for_timeout(500)
                                continue
                            return {"success": True, "buttonText": trimmed[:50]}
                        else:
                            await element.click(timeout=timeout)
                            return {"success": True, "buttonText": trimmed[:50]}
            except Exception:
                pass
    except Exception:
        pass

    return {"success": False, "buttonText": ""}


async def _try_expand_scrollable_lists(page: Page) -> bool:
    """Try expanding scrollable lists that may contain more partners."""
    load_more_patterns = [
        'button:has-text("Load more")',
        'button:has-text("Show more")',
        'button:has-text("View all")',
        '[class*="load-more"]',
        '[class*="show-more"]',
        '[class*="expand"]',
    ]
    for sel in load_more_patterns:
        try:
            button = page.locator(sel).first
            if await button.is_visible(timeout=500):
                await button.click(timeout=1000)
                log.debug("Clicked load more button", {"selector": sel})
                await page.wait_for_timeout(500)
                return True
        except Exception:
            pass
    return False
