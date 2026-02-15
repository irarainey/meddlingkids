"""
Overlay detection and consent-handling pipeline.

Handles the iterative detect → validate → click → extract flow
for cookie-consent banners and other page overlays.

Sub-step functions live in :mod:`overlay_steps` to keep this
module focused on orchestration.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncGenerator

import pydantic
from playwright import async_api

from src.browser import session as browser_session
from src.consent import click, constants, overlay_cache
from src.models import consent, tracking_data
from src.pipeline import overlay_steps, sse_helpers
from src.utils import logger

log = logger.create_logger("Overlays")

MAX_OVERLAYS = 5

# Reject-style button text patterns.  When a cached overlay
# uses one of these, we try to find an accept/allow
# alternative first so the tool maximises consent for analysis.
_REJECT_BUTTON_RE = constants.REJECT_BUTTON_RE

# Accept-style label regex used to locate the preferred button.
_ACCEPT_BUTTON_RE = re.compile(
    r"accept|agree|allow|got it|i understand|okay"
    r"|ok\b|continue|confirm|consent|enable all"
    r"|activate all|opt in|sounds good|sure\b"
    r"|that'?s ok|that'?s fine|no problem|proceed"
    r"|understood|fine\b|yes\b|submit",
    re.IGNORECASE,
)


# ====================================================================
# Result Model
# ====================================================================


def _empty_storage() -> dict[str, list[tracking_data.StorageItem]]:
    return {"local_storage": [], "session_storage": []}


class OverlayHandlingResult(pydantic.BaseModel):
    """Mutable state populated by the overlay handling pipeline."""

    overlay_count: int = 0
    dismissed_overlays: list[consent.CookieConsentDetection] = pydantic.Field(default_factory=list)
    consent_details: consent.ConsentDetails | None = None
    failed: bool = False
    failure_message: str = ""
    final_screenshot: bytes = b""
    final_storage: dict[str, list[tracking_data.StorageItem]] = pydantic.Field(default_factory=_empty_storage)


# ====================================================================
# Accept-button helper
# ====================================================================


async def _find_accept_button(
    frame: async_api.Frame,
) -> str | None:
    """Search *frame* for an accept/allow button.

    Returns the accessible name of the best matching button,
    or ``None`` if none was found.  Prefers buttons whose
    text contains "all" (e.g. "Accept all") for maximum
    consent coverage.
    """
    try:
        locator = frame.get_by_role("button", name=_ACCEPT_BUTTON_RE)
        if await locator.count() > 0:
            # Prefer the button whose text contains "all"
            # (e.g. "Accept all") for maximum consent.
            for i in range(await locator.count()):
                text = await locator.nth(i).inner_text()
                if text and "all" in text.lower():
                    return text.strip()
            # Fall back to the first match.
            text = await locator.first.inner_text()
            return text.strip() if text else None
    except Exception:
        log.debug("Accept button search failed in frame")
    return None


# ====================================================================
# Main Overlay Loop
# ====================================================================


class OverlayPipeline:
    """Encapsulates overlay handling with clean result access.

    Usage::

        pipeline = OverlayPipeline(session, page, screenshot)
        async for event in pipeline.run():
            yield event
        result = pipeline.result
    """

    def __init__(
        self,
        session: browser_session.BrowserSession,
        page: async_api.Page,
        initial_screenshot: bytes,
        domain: str = "",
    ) -> None:
        self._session = session
        self._page = page
        self._initial_screenshot = initial_screenshot
        self._domain = domain
        self.result = OverlayHandlingResult()
        self._cache_dismissed = 0
        self._failed_cache_types: set[str] = set()
        self._new_overlays: list[overlay_cache.CachedOverlay] = []
        self._deferred_extraction: tuple[bytes, str | None] | None = None
        # Mutable state shared across run phases
        self._screenshot: bytes = initial_screenshot
        self._storage: dict = {}
        self._failed_signatures: set[str] = set()
        self._pending_extract: asyncio.Task[list[str]] | None = None
        # High-water mark for progress values.  Ensures that
        # progress events emitted by the overlay pipeline are
        # monotonically increasing regardless of how many
        # overlays are detected or which code path is taken.
        self._progress_hwm = 42  # Phase 3 ("captured") ends at 42

    def _progress(self, step: str, message: str, progress: int) -> str:
        """Format a progress event with a monotonic guarantee.

        Always emits a value >= the highest previously emitted
        value so the client's progress bar never goes backward.
        """
        self._progress_hwm = max(self._progress_hwm, progress)
        return sse_helpers.format_progress_event(step, message, self._progress_hwm)

    def _next_progress_base(self, overlay_count: int) -> int:
        """Compute a monotonically-increasing progress base for an overlay.

        Uses the standard formula ``45 + overlay_count * 5`` but
        ensures the result never falls below the current high-water
        mark, which can happen when cached overlays push the hwm
        above the formula's output for subsequent vision-detected
        overlays.  Also updates the hwm to account for the full
        click-and-capture sequence (base + 3).
        """
        base = max(45 + overlay_count * 5, self._progress_hwm + 1)
        self._progress_hwm = base + 3  # click_and_capture emits up to base+3
        return base

    # ── Shared helpers for vision + cached paths ────────────

    async def _retry_validate_in_dom(
        self,
        detection: consent.CookieConsentDetection,
        *,
        is_first_cookie: bool,
    ) -> async_api.Frame | None:
        """Validate that *detection* exists in the DOM, retrying for first overlays.

        For the first cookie-consent overlay, the dialog
        container may be visible but buttons may still be
        loading (iframe content).  Waits up to 6 s (4 × 1.5 s)
        before giving up.

        Returns the frame where the element was found, or
        ``None`` if not found.
        """
        found = await overlay_steps.validate_overlay_in_dom(self._page, detection)
        if found:
            return found

        if not is_first_cookie:
            return None

        log.info("Cookie-consent button not in DOM — waiting for dialog content to load")
        for _retry in range(4):
            await asyncio.sleep(1.5)
            found = await overlay_steps.validate_overlay_in_dom(self._page, detection)
            if found:
                log.info("Consent button appeared after retry", {"retries": _retry + 1})
                return found
        return None

    async def _prefer_accept_button(
        self,
        detection: consent.CookieConsentDetection,
        found_in_frame: async_api.Frame,
        *,
        fallback_detection: consent.CookieConsentDetection | None = None,
    ) -> tuple[consent.CookieConsentDetection, async_api.Frame | None]:
        """Replace a reject-style detection with an accept alternative.

        If *detection* has reject-style button text, searches
        the DOM for an accept/allow button.  When found, returns
        a new detection + validated frame.  When *not* found,
        returns the provided *fallback_detection* (or the
        original) unchanged.

        Returns:
            ``(detection, found_in_frame)`` — updated or original.
            ``found_in_frame`` is ``None`` when the accept button
            vanished during re-validation and no fallback is set.
        """
        if not (detection.overlay_type == "cookie-consent" and detection.button_text and _REJECT_BUTTON_RE.search(detection.button_text)):
            return detection, found_in_frame

        accept_alt = await _find_accept_button(found_in_frame)
        if not accept_alt:
            return detection, found_in_frame

        log.info(
            "Found accept button — overriding reject",
            {
                "rejectButton": detection.button_text,
                "acceptButton": accept_alt,
            },
        )
        accept_detection = consent.CookieConsentDetection(
            found=True,
            overlay_type="cookie-consent",
            selector=None,
            button_text=accept_alt,
            confidence=detection.confidence,
            reason="accept preferred over reject",
        )
        alt_frame = await overlay_steps.validate_overlay_in_dom(self._page, accept_detection)
        if alt_frame:
            return accept_detection, alt_frame

        # Accept button vanished between search and validation —
        # fall back to the original or caller-provided fallback.
        log.warn("Accept button not found on re-validation — using original detection")
        if fallback_detection:
            return fallback_detection, found_in_frame
        return detection, found_in_frame

    async def run(self) -> AsyncGenerator[str]:
        """Handle overlays, yielding SSE events.

        Populates ``self.result`` as side-state so the caller
        can read the final overlay outcome after iteration.

        Tracks selectors/button-text combinations that already
        failed to click so we don't re-detect and waste time
        on the same unclickable element.
        """
        result = self.result
        self._storage = await self._session.capture_storage()
        result.final_storage = self._storage

        log.info(
            "Starting overlay detection loop",
            {"maxOverlays": MAX_OVERLAYS},
        )

        # ── Try cached overlay strategy first ───────────
        cached_entry = overlay_cache.load(self._domain) if self._domain else None
        if cached_entry:
            async for event in self._try_cached_overlays(
                cached_entry,
                result,
                self._session,
                self._page,
            ):
                yield event
            if self._cache_dismissed > 0:
                self._screenshot = await self._session.take_screenshot(full_page=False)
                self._storage = await self._session.capture_storage()

                if self._deferred_extraction:
                    ext_screenshot, ext_text = self._deferred_extraction
                    self._deferred_extraction = None
                    self._pending_extract = asyncio.create_task(
                        overlay_steps.collect_extraction_events(
                            self._page,
                            ext_screenshot,
                            result,
                            pre_click_consent_text=ext_text,
                        )
                    )

        # ── Vision detection loop ───────────────────────
        async for event in self._run_vision_loop():
            yield event

        # Collect any pending extraction.
        if self._pending_extract is not None:
            extract_events = await self._pending_extract
            self._pending_extract = None
            for event in extract_events:
                yield event

        overlay_count = result.overlay_count
        if overlay_count >= MAX_OVERLAYS:
            log.warn("Reached maximum overlay limit, stopping detection")
            yield self._progress(
                "overlays-limit",
                "Maximum overlay limit reached...",
                70,
            )

        result.final_screenshot = self._screenshot
        result.final_storage = self._storage

        # ── Persist / merge cache ───────────────────────
        if result.overlay_count > 0 and not result.failed and self._domain:
            self._save_cache(cached_entry)

    async def _run_vision_loop(self) -> AsyncGenerator[str]:
        """Run the vision-based overlay detection loop.

        Always runs after the cached overlay strategy to catch
        overlays that the cache didn't cover.  Yields SSE events
        and updates ``self.result`` as side-state.
        """
        result = self.result
        session = self._session
        overlay_count = result.overlay_count

        # Let the user know what's happening next.
        if overlay_count > 0:
            if self._pending_extract is not None:
                log.info("Analyzing overlay concurrently with verification")
                yield self._progress(
                    "consent-analyze",
                    "Analyzing page for overlay...",
                    68,
                )
            else:
                log.info("Checking for additional overlays after dismissal")
                yield self._progress(
                    "overlays-verify",
                    "Checking for additional overlays...",
                    68,
                )

        while overlay_count < MAX_OVERLAYS:
            # ── Detect ──────────────────────────────────────
            detection = await overlay_steps.detect_overlay(session, overlay_count)

            if not detection.found or (not detection.selector and not detection.button_text):
                for event in overlay_steps.build_no_overlay_events(overlay_count, detection.reason):
                    yield event
                break

            # ── Check for repeated detection ────────────────
            sig = overlay_steps.detection_signature(detection)
            if sig in self._failed_signatures:
                log.warn(
                    "Skipping re-detected overlay that already failed to click",
                    {
                        "selector": detection.selector,
                        "buttonText": detection.button_text,
                    },
                )
                for event in overlay_steps.build_no_overlay_events(
                    overlay_count,
                    "Overlay re-detected but click already failed — stopping",
                ):
                    yield event
                break

            # ── Validate in DOM ─────────────────────────────
            is_first_cookie = detection.overlay_type == "cookie-consent" and overlay_count == 0
            found_in_frame = await self._retry_validate_in_dom(
                detection,
                is_first_cookie=is_first_cookie,
            )
            if not found_in_frame:
                for event in overlay_steps.build_no_overlay_events(
                    overlay_count,
                    "Detection false positive — element not found in DOM",
                ):
                    yield event
                break

            # ── Prefer accept over LLM-detected reject ─────
            detection, found_in_frame = await self._prefer_accept_button(detection, found_in_frame)
            if not found_in_frame:
                detection = await overlay_steps.detect_overlay(session, overlay_count)
                found_in_frame = await self._retry_validate_in_dom(
                    detection,
                    is_first_cookie=False,
                )
                if not found_in_frame:
                    for event in overlay_steps.build_no_overlay_events(
                        overlay_count,
                        "Accept override failed and re-detection lost the element",
                    ):
                        yield event
                    break

            overlay_count += 1
            progress_base = self._next_progress_base(overlay_count)

            log.info(
                f"Overlay {overlay_count} found (validated in DOM)",
                {
                    "type": detection.overlay_type,
                    "selector": detection.selector,
                    "buttonText": detection.button_text,
                    "confidence": detection.confidence,
                },
            )
            yield self._progress(
                f"overlay-{overlay_count}-found",
                overlay_steps.get_overlay_message(detection.overlay_type),
                progress_base,
            )
            result.dismissed_overlays.append(detection)

            # ── Click and capture ───────────────────────────
            should_break = False
            async for event in self._click_and_capture(
                detection,
                found_in_frame,
                overlay_count,
                progress_base,
                sig,
            ):
                if event == "__BREAK__":
                    should_break = True
                else:
                    yield event
            if should_break:
                break

        result.overlay_count = overlay_count

    async def _click_and_capture(
        self,
        detection: consent.CookieConsentDetection,
        found_in_frame: async_api.Frame,
        overlay_number: int,
        progress_base: int,
        sig: str,
    ) -> AsyncGenerator[str]:
        """Capture consent content, click the overlay, and handle the outcome.

        Yields SSE event strings.  Yields the sentinel ``"__BREAK__"``
        if the caller's detection loop should stop.

        Args:
            detection: The overlay detection to click.
            found_in_frame: Frame where the element was validated.
            overlay_number: 1-based overlay counter.
            progress_base: Progress bar base value for this overlay.
            sig: Detection signature for dedup tracking.
        """
        result = self.result
        session = self._session
        page = self._page
        is_first_cookie_consent = detection.overlay_type == "cookie-consent" and not result.consent_details

        # ── Capture consent content before dismissing ───
        pre_click_screenshot: bytes | None = None
        pre_click_consent_text: str | None = None
        if is_first_cookie_consent:
            yield self._progress(
                f"overlay-{overlay_number}-capture",
                "Inspecting overlay content...",
                progress_base,
            )
            pre_click_consent_text, pre_click_screenshot = await overlay_steps.capture_consent_content(page, session)

        # ── Click ───────────────────────────────────────
        yield self._progress(
            f"overlay-{overlay_number}-click",
            "Dismissing overlay...",
            progress_base + 1,
        )

        try:
            click_result = await overlay_steps.try_overlay_click(
                page,
                detection,
                overlay_number,
                found_in_frame=found_in_frame,
            )

            if not click_result.success:
                self._failed_signatures.add(sig)

                if is_first_cookie_consent and pre_click_screenshot:
                    log.info(
                        "Click failed but pre-click consent data available — preserving for analysis",
                        {"textLength": len(pre_click_consent_text or "")},
                    )
                    self._pending_extract = asyncio.create_task(
                        overlay_steps.collect_extraction_events(
                            page,
                            pre_click_screenshot,
                            result,
                            pre_click_consent_text=pre_click_consent_text,
                        )
                    )

                event, msg = overlay_steps.build_click_failure(detection, overlay_number)
                if overlay_number == 1:
                    log.error("Failed to click first overlay, aborting analysis")
                    result.failed = True
                    result.failure_message = msg
                    yield event
                else:
                    log.warn(
                        f"Failed to click overlay {overlay_number}, continuing analysis",
                        {"type": detection.overlay_type},
                    )
                yield "__BREAK__"
                return

            # Click succeeded — capture post-click state
            async for event in overlay_steps.capture_after_click(
                session,
                page,
                detection,
                overlay_number,
                progress_base,
            ):
                yield event

            self._new_overlays.append(
                overlay_cache.CachedOverlay(
                    overlay_type=detection.overlay_type or "other",
                    button_text=detection.button_text,
                    css_selector=detection.selector,
                    locator_strategy=click_result.strategy or "role-button",
                    frame_type=click_result.frame_type or "main",
                )
            )

            self._screenshot = await session.take_screenshot(full_page=False)
            self._storage = await session.capture_storage()

        except Exception as click_error:
            self._failed_signatures.add(sig)

            if is_first_cookie_consent and pre_click_screenshot:
                log.info(
                    "Click errored but pre-click consent data available — preserving for analysis",
                )
                if self._pending_extract is not None:
                    await self._pending_extract
                self._pending_extract = asyncio.create_task(
                    overlay_steps.collect_extraction_events(
                        page,
                        pre_click_screenshot,
                        result,
                        pre_click_consent_text=pre_click_consent_text,
                    )
                )

            event, msg = overlay_steps.build_click_failure(
                detection,
                overlay_number,
                error_detail=str(click_error),
            )
            if overlay_number == 1:
                log.error(
                    "Failed to click first overlay",
                    {"error": str(click_error)},
                )
                result.failed = True
                result.failure_message = msg
                yield event
            else:
                log.warn(
                    f"Failed to click overlay {overlay_number}, continuing analysis",
                    {"error": str(click_error)},
                )
            yield "__BREAK__"
            return

        # ── Consent extraction (first cookie only) ──────
        if is_first_cookie_consent and pre_click_screenshot:
            if self._pending_extract is not None:
                await self._pending_extract
            self._pending_extract = asyncio.create_task(
                overlay_steps.collect_extraction_events(
                    page,
                    pre_click_screenshot,
                    result,
                    pre_click_consent_text=pre_click_consent_text,
                )
            )

    # ── Cached overlay helpers ──────────────────────────────

    async def _try_cached_overlays(
        self,
        entry: overlay_cache.OverlayCacheEntry,
        result: OverlayHandlingResult,
        session: browser_session.BrowserSession,
        page: async_api.Page,
    ) -> AsyncGenerator[str]:
        """Attempt to dismiss overlays using cached info.

        Each cached overlay is tried independently:

        - **Not in DOM** → skipped (kept in cache for other
          pages on the same domain).
        - **In DOM, click succeeds** → counted as dismissed.
        - **In DOM, click fails** → recorded in
          ``_failed_cache_types`` so the save step can drop
          the stale entry.

        Yields SSE events in real-time.  Sets
        ``self._cache_dismissed`` so the caller can read the
        count after iteration.
        """
        self._failed_cache_types.clear()
        self._deferred_extraction = None
        dismissed = 0

        log.info(
            "Attempting cached overlay dismissal",
            {
                "domain": entry.domain,
                "cachedOverlays": len(entry.overlays),
            },
        )

        for cached in entry.overlays:
            # Build a synthetic detection from cache
            detection = consent.CookieConsentDetection(
                found=True,
                overlay_type=(
                    cached.overlay_type  # type: ignore[arg-type]
                ),
                selector=cached.css_selector,
                button_text=cached.button_text,
                confidence="high",
                reason="from overlay cache",
            )

            # Validate element exists in DOM
            is_first_cookie = cached.overlay_type == "cookie-consent" and dismissed == 0
            found_in_frame = await self._retry_validate_in_dom(
                detection,
                is_first_cookie=is_first_cookie,
            )
            if not found_in_frame:
                # Not shown on this page — skip but keep
                # in cache for other pages on the domain.
                log.info(
                    "Cached overlay not present on this page — skipping",
                    {
                        "type": cached.overlay_type,
                        "buttonText": cached.button_text,
                    },
                )
                continue

            # ── Prefer accept over cached reject ───────
            detection, found_in_frame = await self._prefer_accept_button(
                detection,
                found_in_frame,
                fallback_detection=detection,
            )

            overlay_number = result.overlay_count + dismissed + 1
            progress_base = self._next_progress_base(overlay_number)

            log.info(
                f"Cached overlay {overlay_number} validated in DOM",
                {
                    "type": cached.overlay_type,
                    "buttonText": detection.button_text,
                    "locatorStrategy": cached.locator_strategy,
                    "frameType": cached.frame_type,
                },
            )

            yield self._progress(
                f"overlay-{overlay_number}-found",
                overlay_steps.get_overlay_message(cached.overlay_type),
                progress_base,
            )

            is_first_cookie = cached.overlay_type == "cookie-consent" and not result.consent_details

            # ── Capture consent content before dismissing ───
            pre_click_screenshot: bytes | None = None
            pre_click_consent_text: str | None = None
            if is_first_cookie:
                yield self._progress(
                    f"overlay-{overlay_number}-capture",
                    "Inspecting overlay content...",
                    progress_base,
                )
                pre_click_consent_text, pre_click_screenshot = await overlay_steps.capture_consent_content(page, session)

            yield self._progress(
                f"overlay-{overlay_number}-click",
                "Dismissing overlay...",
                progress_base + 1,
            )

            # Attempt click
            try:
                click_result = await overlay_steps.try_overlay_click(
                    page,
                    detection,
                    overlay_number,
                    found_in_frame=found_in_frame,
                )
            except Exception as exc:
                log.warn(
                    "Cached overlay click error",
                    {
                        "overlay": overlay_number,
                        "error": str(exc),
                    },
                )
                click_result = click.ClickResult(success=False)

            if click_result.success:
                async for event in overlay_steps.capture_after_click(
                    session,
                    page,
                    detection,
                    overlay_number,
                    progress_base,
                ):
                    yield event

                dismissed += 1
                result.dismissed_overlays.append(detection)

                self._new_overlays.append(
                    overlay_cache.CachedOverlay(
                        overlay_type=detection.overlay_type or "other",
                        button_text=detection.button_text,
                        css_selector=detection.selector,
                        locator_strategy=click_result.strategy or "role-button",
                        frame_type=click_result.frame_type or "main",
                    )
                )

                # Defer consent extraction — it will run
                # concurrently with the verification vision
                # detect call for ~7-8s time saving.
                if is_first_cookie and pre_click_screenshot:
                    self._deferred_extraction = (
                        pre_click_screenshot,
                        pre_click_consent_text,
                    )
            else:
                log.info(
                    "Cached overlay click failed — entry will be dropped from cache",
                    {
                        "overlay": overlay_number,
                        "type": cached.overlay_type,
                    },
                )
                self._failed_cache_types.add(cached.overlay_type)
                # Preserve pre-click consent data even
                # when the cached click fails so consent
                # analysis is still included in the report.
                if is_first_cookie and pre_click_screenshot:
                    log.info(
                        "Cached click failed but pre-click consent data available — preserving for analysis",
                    )
                    self._deferred_extraction = (
                        pre_click_screenshot,
                        pre_click_consent_text,
                    )

        result.overlay_count += dismissed
        self._cache_dismissed = dismissed

        if dismissed > 0:
            log.success(
                "Cached overlays dismissed",
                {
                    "domain": entry.domain,
                    "dismissed": dismissed,
                    "skipped": (len(entry.overlays) - dismissed - len(self._failed_cache_types)),
                },
            )
        else:
            log.info(
                "No cached overlays matched this page",
                {"domain": entry.domain},
            )

    def _save_cache(
        self,
        previous_entry: (overlay_cache.OverlayCacheEntry | None) = None,
    ) -> None:
        """Merge and persist a cache entry.

        Uses the ``_new_overlays`` list built during the click
        pipeline, which already contains the correct Playwright
        locator strategy and frame type for each successfully
        dismissed overlay.
        """
        overlay_cache.merge_and_save(
            self._domain,
            previous_entry,
            self._new_overlays,
            self._failed_cache_types,
        )
