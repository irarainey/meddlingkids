"""
Overlay detection and consent-handling pipeline.

Handles the iterative detect → validate → click → extract flow
for cookie-consent banners and other page overlays.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import pydantic
from playwright import async_api

from src.browser import session as browser_session
from src.consent import (
    click,
    extraction,
    overlay_cache,
    partner_classification,
)
from src.consent import detection as consent_detection_mod
from src.models import consent, tracking_data
from src.pipeline import sse_helpers
from src.utils import logger

log = logger.create_logger("Overlays")

MAX_OVERLAYS = 5


# ====================================================================
# Result Model
# ====================================================================


def _empty_storage() -> dict[str, list[tracking_data.StorageItem]]:
    return {"local_storage": [], "session_storage": []}


class OverlayHandlingResult(pydantic.BaseModel):
    """Mutable state populated by the overlay handling pipeline."""

    overlay_count: int = 0
    dismissed_overlays: list[
        consent.CookieConsentDetection
    ] = pydantic.Field(default_factory=list)
    consent_details: consent.ConsentDetails | None = None
    failed: bool = False
    failure_message: str = ""
    final_screenshot: bytes = b""
    final_storage: dict[
        str, list[tracking_data.StorageItem]
    ] = pydantic.Field(default_factory=_empty_storage)


# ====================================================================
# Sub-steps
# ====================================================================


def _get_overlay_message(overlay_type: str | None) -> str:
    """Get appropriate message based on overlay type."""
    messages = {
        "cookie-consent": "Cookie consent detected",
        "sign-in": "Sign-in prompt detected",
        "newsletter": "Newsletter popup detected",
        "paywall": "Paywall detected",
        "age-verification": "Age verification detected",
    }
    return messages.get(overlay_type or "", "Overlay detected")


async def _detect_overlay(
    session: browser_session.BrowserSession,
    iteration: int,
) -> consent.CookieConsentDetection:
    """Run AI overlay detection on the current page state.

    Uses vision-only detection — the LLM analyses the screenshot
    to identify cookie consent dialogs and their dismiss buttons.

    Takes a viewport-only screenshot for detection (overlays are
    always visible in the viewport) to reduce image size and
    speed up LLM inference.
    """
    log.start_timer(f"overlay-detect-{iteration + 1}")

    # Use a viewport-only screenshot for faster detection.
    # Overlays always cover the viewport, so full-page is unnecessary.
    viewport_screenshot = await session.take_screenshot(full_page=False)
    log.debug("Running overlay detection", {
        "iteration": iteration + 1,
        "screenshotBytes": len(viewport_screenshot),
    })

    detection = await consent_detection_mod.detect_cookie_consent(
        viewport_screenshot
    )
    log.end_timer(
        f"overlay-detect-{iteration + 1}",
        "Overlay detection complete",
    )
    return detection


async def _validate_overlay_in_dom(
    page: async_api.Page,
    detection: consent.CookieConsentDetection,
) -> async_api.Frame | None:
    """Check that the LLM-detected element actually exists in the DOM.

    Guards against false positives where the LLM hallucinates
    overlays from ads or page furniture.

    Returns the frame where the element was found, or ``None``
    if it wasn't found anywhere.
    """
    found_frame = await click.validate_element_exists(
        page, detection.selector, detection.button_text
    )
    if not found_frame:
        log.warn(
            "Overlay detected by LLM but element not found in"
            " DOM — treating as false positive",
            {
                "selector": detection.selector,
                "buttonText": detection.button_text,
            },
        )
    return found_frame


async def _click_and_capture(
    session: browser_session.BrowserSession,
    page: async_api.Page,
    detection: consent.CookieConsentDetection,
    overlay_number: int,
    progress_base: int,
    *,
    found_in_frame: async_api.Frame | None = None,
) -> AsyncGenerator[str, None]:
    """Click the overlay dismiss button and capture resulting state.

    Yields SSE events for progress, the post-click screenshot,
    and the consent detection event.  The first value yielded
    is always a ``bool`` indicating whether the click succeeded,
    followed by SSE event strings on success.
    """
    log.start_timer(f"overlay-click-{overlay_number}")

    clicked = await click.try_click_consent_button(
        page, detection.selector, detection.button_text,
        found_in_frame=found_in_frame,
    )
    log.end_timer(
        f"overlay-click-{overlay_number}",
        "Click succeeded" if clicked else "Click failed",
    )

    if not clicked:
        return

    yield sse_helpers.format_progress_event(
        f"overlay-{overlay_number}-wait",
        "Waiting for page to update...",
        progress_base + 2,
    )

    # Wait for DOM to settle (race timeout vs load state)
    _, pending = await asyncio.wait(
        [
            asyncio.create_task(session.wait_for_timeout(800)),
            asyncio.create_task(
                session.wait_for_load_state("domcontentloaded")
            ),
        ],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    yield sse_helpers.format_progress_event(
        f"overlay-{overlay_number}-capture",
        "Capturing page state...",
        progress_base + 3,
    )
    await session.capture_current_cookies()

    event_str, _, _ = await sse_helpers.take_screenshot_event(
        session,
        extra={"overlayDismissed": detection.overlay_type},
    )
    yield event_str

    log.success(
        f"Overlay {overlay_number} ({detection.overlay_type})"
        " dismissed successfully"
    )

    yield sse_helpers.format_sse_event(
        "consent",
        {
            "detected": True,
            "clicked": True,
            "details": {
                "found": detection.found,
                "overlayType": detection.overlay_type,
                "selector": detection.selector,
                "buttonText": detection.button_text,
                "confidence": detection.confidence,
                "reason": detection.reason,
            },
            "overlayNumber": overlay_number,
        },
    )


async def _extract_and_classify_consent(
    page: async_api.Page,
    pre_click_screenshot: bytes,
    result: OverlayHandlingResult,
    progress_base: int,
) -> AsyncGenerator[str, None]:
    """Extract consent details and classify partner risk levels.

    Only called for the first cookie-consent overlay after a
    successful click.  Uses the pre-click screenshot so the
    consent dialog is still visible for the extraction agent.
    """
    log.start_timer("consent-extraction")
    yield sse_helpers.format_progress_event(
        "consent-extract",
        "Analyzing page content...",
        progress_base + 4,
    )
    result.consent_details = (
        await extraction.extract_consent_details(
            page, pre_click_screenshot
        )
    )
    log.end_timer("consent-extraction", "Consent details extracted")
    log.info(
        "Consent details",
        {
            "categories": len(result.consent_details.categories),
            "partners": len(result.consent_details.partners),
            "purposes": len(result.consent_details.purposes),
        },
    )

    # Enrich partners with risk classification
    if result.consent_details.partners:
        log.start_timer("partner-classification")
        yield sse_helpers.format_progress_event(
            "partner-classify",
            "Analyzing partner risk levels...",
            progress_base + 5,
        )

        risk_summary = partner_classification.get_partner_risk_summary(
            result.consent_details.partners
        )
        log.info(
            "Partner risk summary",
            {
                "critical": risk_summary.critical_count,
                "high": risk_summary.high_count,
                "totalRisk": risk_summary.total_risk_score,
            },
        )

        for partner in result.consent_details.partners:
            classification = (
                partner_classification.classify_partner_by_pattern_sync(
                    partner
                )
            )
            if classification:
                partner.risk_level = classification.risk_level
                partner.risk_category = classification.category
                partner.risk_score = classification.risk_score
                partner.concerns = classification.concerns
            else:
                partner.risk_level = "unknown"
                partner.risk_score = 3

        log.end_timer(
            "partner-classification",
            "Partner classification complete",
        )

    yield sse_helpers.format_sse_event(
        "consentDetails",
        sse_helpers.serialize_consent_details(result.consent_details),
    )


def _build_no_overlay_events(
    overlay_count: int,
    reason: str | None,
) -> list[str]:
    """Build SSE events for the 'no overlay found' case."""
    if overlay_count == 0:
        log.info("No overlay detected", {"reason": reason})
        return [
            sse_helpers.format_progress_event(
                "consent-none", "No overlay detected...", 70
            ),
            sse_helpers.format_sse_event(
                "consent",
                {
                    "detected": False,
                    "clicked": False,
                    "details": None,
                    "reason": reason,
                },
            ),
        ]
    log.success(
        f"Dismissed {overlay_count} overlay(s), no more found"
    )
    return [
        sse_helpers.format_progress_event(
            "overlays-done",
            f"Dismissed {overlay_count} overlay(s)...",
            70,
        )
    ]


def _build_click_failure(
    detection: consent.CookieConsentDetection,
    overlay_number: int,
    error_detail: str | None = None,
) -> tuple[str, str]:
    """Build click failure SSE event and message."""
    if error_detail:
        msg = (
            f"Failed to dismiss"
            f" {detection.overlay_type or 'overlay'}:"
            f" {error_detail}"
        )
    else:
        msg = (
            f"Failed to dismiss"
            f" {detection.overlay_type or 'overlay'}"
            f" (button:"
            f" '{detection.button_text or detection.selector}')"
        )

    event = sse_helpers.format_sse_event(
        "consent",
        {
            "detected": True,
            "clicked": False,
            "details": {
                "found": detection.found,
                "overlayType": detection.overlay_type,
                "selector": detection.selector,
                "buttonText": detection.button_text,
                "confidence": detection.confidence,
                "reason": detection.reason,
            },
            "error": msg,
            "overlayNumber": overlay_number,
        },
    )
    return event, msg


async def _collect_extraction_events(
    page: async_api.Page,
    pre_click_screenshot: bytes,
    result: OverlayHandlingResult,
    progress_base: int,
) -> list[str]:
    """Run consent extraction, returning events for deferred yielding.

    Used when extraction runs concurrently with the next
    detection call to avoid blocking the overlay loop.
    """
    events: list[str] = []
    async for event in _extract_and_classify_consent(
        page, pre_click_screenshot, result, progress_base
    ):
        events.append(event)
    return events


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
        self._deferred_extraction: (
            tuple[bytes, int] | None
        ) = None

    async def run(self) -> AsyncGenerator[str, None]:
        """Handle overlays, yielding SSE events.

        Populates ``self.result`` as side-state so the caller
        can read the final overlay outcome after iteration.

        Tracks selectors/button-text combinations that already
        failed to click so we don't re-detect and waste time
        on the same unclickable element.
        """
        result = self.result
        session = self._session
        page = self._page
        screenshot = self._initial_screenshot
        storage = await session.capture_storage()
        result.final_storage = storage

        # Track selectors that already failed clicking so we
        # don't loop on the same unclickable element.
        failed_signatures: set[str] = set()

        # Pending extraction task — runs concurrently with
        # the next detection call to save ~8s per overlay.
        pending_extract: asyncio.Task[list[str]] | None = None

        log.info(
            "Starting overlay detection loop",
            {"maxOverlays": MAX_OVERLAYS},
        )

        # ── Try cached overlay strategy first ───────────
        cached_entry = (
            overlay_cache.load(self._domain)
            if self._domain
            else None
        )
        if cached_entry:
            async for event in self._try_cached_overlays(
                cached_entry, result, session, page,
            ):
                yield event
            if self._cache_dismissed > 0:
                screenshot = (
                    await session.take_screenshot(
                        full_page=False
                    )
                )
                storage = await session.capture_storage()

                # Start deferred consent extraction as a
                # background task so it runs concurrently
                # with the verification vision detect.
                if self._deferred_extraction:
                    ext_screenshot, ext_progress = (
                        self._deferred_extraction
                    )
                    self._deferred_extraction = None
                    pending_extract = asyncio.create_task(
                        _collect_extraction_events(
                            page,
                            ext_screenshot,
                            result,
                            ext_progress,
                        )
                    )

        # Always run vision detection to catch overlays
        # that the cache didn't cover (different pages
        # on the same domain may show different subsets).
        overlay_count = result.overlay_count

        # Let the user know what's happening next.
        if overlay_count > 0:
            if pending_extract is not None:
                # Consent extraction is the dominant task
                # (runs concurrently with overlay verify).
                yield sse_helpers.format_progress_event(
                    "consent-analyze",
                    "Analyzing consent details...",
                    68,
                )
            else:
                yield sse_helpers.format_progress_event(
                    "overlays-verify",
                    "Checking for additional overlays...",
                    68,
                )

        while overlay_count < MAX_OVERLAYS:
            # ── Detect (concurrent with pending extraction) ─
            if pending_extract is not None:
                detection, extract_events = (
                    await asyncio.gather(
                        _detect_overlay(
                            session, overlay_count
                        ),
                        pending_extract,
                    )
                )
                pending_extract = None
                for event in extract_events:
                    yield event
            else:
                detection = await _detect_overlay(
                    session, overlay_count
                )

            if not detection.found or (
                not detection.selector
                and not detection.button_text
            ):
                for event in _build_no_overlay_events(
                    overlay_count, detection.reason
                ):
                    yield event
                break

            # ── Check for repeated detection ────────────────
            sig = _detection_signature(detection)
            if sig in failed_signatures:
                log.warn(
                    "Skipping re-detected overlay that"
                    " already failed to click",
                    {
                        "selector": detection.selector,
                        "buttonText": detection.button_text,
                    },
                )
                for event in _build_no_overlay_events(
                    overlay_count,
                    "Overlay re-detected but click already"
                    " failed — stopping",
                ):
                    yield event
                break

            # ── Validate in DOM ─────────────────────────────
            found_in_frame = await _validate_overlay_in_dom(
                page, detection
            )
            if not found_in_frame:
                for event in _build_no_overlay_events(
                    overlay_count,
                    "Detection false positive — element not"
                    " found in DOM",
                ):
                    yield event
                break

            overlay_count += 1
            progress_base = 45 + (overlay_count * 5)

            log.info(
                f"Overlay {overlay_count} found"
                " (validated in DOM)",
                {
                    "type": detection.overlay_type,
                    "selector": detection.selector,
                    "buttonText": detection.button_text,
                    "confidence": detection.confidence,
                },
            )
            yield sse_helpers.format_progress_event(
                f"overlay-{overlay_count}-found",
                _get_overlay_message(detection.overlay_type),
                progress_base,
            )
            result.dismissed_overlays.append(detection)

            is_first_cookie_consent = (
                detection.overlay_type == "cookie-consent"
                and not result.consent_details
            )
            pre_click_screenshot = (
                screenshot
                if is_first_cookie_consent
                else None
            )

            # ── Click ───────────────────────────────────────
            yield sse_helpers.format_progress_event(
                f"overlay-{overlay_count}-click",
                "Dismissing overlay...",
                progress_base + 1,
            )

            try:
                clicked = False
                async for event in _click_and_capture(
                    session,
                    page,
                    detection,
                    overlay_count,
                    progress_base,
                    found_in_frame=found_in_frame,
                ):
                    clicked = True
                    yield event

                if not clicked:
                    # Record this detection so we don't
                    # waste time re-detecting it.
                    failed_signatures.add(sig)

                    event, msg = _build_click_failure(
                        detection, overlay_count
                    )
                    if overlay_count == 1:
                        log.error(
                            "Failed to click first overlay,"
                            " aborting analysis"
                        )
                        result.failed = True
                        result.failure_message = msg
                        yield event
                    else:
                        log.warn(
                            f"Failed to click overlay"
                            f" {overlay_count},"
                            " continuing analysis",
                            {
                                "type": (
                                    detection.overlay_type
                                ),
                            },
                        )
                    break

                # Update screenshot for next iteration
                screenshot = (
                    await session.take_screenshot(
                        full_page=False
                    )
                )
                storage = await session.capture_storage()

            except Exception as click_error:
                failed_signatures.add(sig)
                event, msg = _build_click_failure(
                    detection,
                    overlay_count,
                    error_detail=str(click_error),
                )
                if overlay_count == 1:
                    log.error(
                        "Failed to click first overlay",
                        {"error": str(click_error)},
                    )
                    result.failed = True
                    result.failure_message = msg
                    yield event
                else:
                    log.warn(
                        f"Failed to click overlay"
                        f" {overlay_count},"
                        " continuing analysis",
                        {"error": str(click_error)},
                    )
                break

            # ── Consent extraction (first cookie only) ──────
            # Start extraction as a background task so it runs
            # concurrently with the next detection call.
            if (
                is_first_cookie_consent
                and pre_click_screenshot
            ):
                pending_extract = asyncio.create_task(
                    _collect_extraction_events(
                        page,
                        pre_click_screenshot,
                        result,
                        progress_base,
                    )
                )

        # Collect any pending extraction that was started
        # during the final loop iteration.
        if pending_extract is not None:
            extract_events = await pending_extract
            pending_extract = None
            for event in extract_events:
                yield event

        if overlay_count >= MAX_OVERLAYS:
            log.warn(
                "Reached maximum overlay limit,"
                " stopping detection"
            )
            yield sse_helpers.format_progress_event(
                "overlays-limit",
                "Maximum overlay limit reached...",
                70,
            )

        result.overlay_count = overlay_count
        result.final_screenshot = screenshot
        result.final_storage = storage

        # ── Persist / merge cache ───────────────────────
        if (
            result.overlay_count > 0
            and not result.failed
            and self._domain
        ):
            self._save_cache(result, cached_entry)

    # ── Cached overlay helpers ──────────────────────────────

    async def _try_cached_overlays(
        self,
        entry: overlay_cache.OverlayCacheEntry,
        result: OverlayHandlingResult,
        session: browser_session.BrowserSession,
        page: async_api.Page,
    ) -> AsyncGenerator[str, None]:
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
        self._failed_cache_types: set[str] = set()
        self._deferred_extraction: (
            tuple[bytes, int] | None
        ) = None
        dismissed = 0
        # Track the latest screenshot so consent extraction
        # gets the correct pre-click image (showing the
        # cookie dialog, not an earlier overlay).
        latest_screenshot = self._initial_screenshot

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
                selector=cached.selector,
                button_text=cached.button_text,
                confidence="high",
                reason="from overlay cache",
            )

            # Validate element exists in DOM
            found_in_frame = await _validate_overlay_in_dom(
                page, detection
            )
            if not found_in_frame:
                # Not shown on this page — skip but keep
                # in cache for other pages on the domain.
                log.info(
                    "Cached overlay not present on this"
                    " page — skipping",
                    {
                        "type": cached.overlay_type,
                        "buttonText": cached.button_text,
                    },
                )
                continue

            overlay_number = (
                result.overlay_count + dismissed + 1
            )
            progress_base = 45 + (overlay_number * 5)

            log.info(
                f"Cached overlay {overlay_number}"
                " validated in DOM",
                {
                    "type": cached.overlay_type,
                    "buttonText": cached.button_text,
                    "accessorType": cached.accessor_type,
                },
            )

            yield sse_helpers.format_progress_event(
                f"overlay-{overlay_number}-found",
                _get_overlay_message(
                    cached.overlay_type
                ),
                progress_base,
            )
            result.dismissed_overlays.append(detection)

            is_first_cookie = (
                cached.overlay_type == "cookie-consent"
                and not result.consent_details
            )
            # Use the latest screenshot (updated after each
            # successful click) so the consent extraction
            # agent sees the cookie dialog, not an earlier
            # overlay like sign-in.
            pre_click_screenshot = (
                latest_screenshot
                if is_first_cookie
                else None
            )

            yield sse_helpers.format_progress_event(
                f"overlay-{overlay_number}-click",
                "Dismissing overlay (cached)...",
                progress_base + 1,
            )

            # Attempt click — stream events in real-time
            click_ok = False
            try:
                async for event in _click_and_capture(
                    session,
                    page,
                    detection,
                    overlay_number,
                    progress_base,
                    found_in_frame=found_in_frame,
                ):
                    click_ok = True
                    yield event
            except Exception as exc:
                log.warn(
                    "Cached overlay click error",
                    {
                        "overlay": overlay_number,
                        "error": str(exc),
                    },
                )

            if click_ok:
                dismissed += 1
                # Update latest screenshot so subsequent
                # overlays (and consent extraction) get the
                # correct page state.
                latest_screenshot = (
                    await session.take_screenshot(
                        full_page=False
                    )
                )

                # Defer consent extraction — it will run
                # concurrently with the verification vision
                # detect call for ~7-8s time saving.
                if is_first_cookie and pre_click_screenshot:
                    self._deferred_extraction = (
                        pre_click_screenshot,
                        progress_base,
                    )
            else:
                log.info(
                    "Cached overlay click failed"
                    " — entry will be dropped from cache",
                    {
                        "overlay": overlay_number,
                        "type": cached.overlay_type,
                    },
                )
                self._failed_cache_types.add(
                    cached.overlay_type
                )
                # Remove from dismissed_overlays list
                result.dismissed_overlays.pop()

        result.overlay_count += dismissed
        self._cache_dismissed = dismissed

        if dismissed > 0:
            log.success(
                "Cached overlays dismissed",
                {
                    "domain": entry.domain,
                    "dismissed": dismissed,
                    "skipped": (
                        len(entry.overlays) - dismissed
                        - len(self._failed_cache_types)
                    ),
                },
            )
        else:
            log.info(
                "No cached overlays matched this page",
                {"domain": entry.domain},
            )

    def _save_cache(
        self,
        result: OverlayHandlingResult,
        previous_entry: (
            overlay_cache.OverlayCacheEntry | None
        ) = None,
    ) -> None:
        """Merge and persist a cache entry.

        Combines three sources:

        1. Previous cache entries whose overlays were *not
           present on this page* (skipped) and did not fail.
        2. Overlays dismissed via vision detection on this
           run (new discoveries).
        3. Cached overlays that were present and clicked
           successfully are already captured in (1) or (2)
           via ``result.dismissed_overlays``.

        Entries whose clicks failed (tracked in
        ``_failed_cache_types``) are dropped.
        """
        failed_attr = getattr(
            self, "_failed_cache_types", None
        )
        failed = failed_attr if failed_attr else set[str]()
        seen_keys: set[str] = set()
        overlays: list[overlay_cache.CachedOverlay] = []

        def _key(
            button: str | None, selector: str | None
        ) -> str:
            return f"{selector or ''}|{button or ''}"

        # Carry forward previous cache entries that were
        # skipped (not on this page) and didn't fail.
        if previous_entry:
            for cached in previous_entry.overlays:
                if cached.overlay_type in failed:
                    continue
                key = _key(
                    cached.button_text, cached.selector
                )
                if key not in seen_keys:
                    seen_keys.add(key)
                    overlays.append(cached)

        # Add overlays from this run's detections.
        for detection in result.dismissed_overlays:
            accessor = _infer_accessor_type(detection)
            key = _key(
                detection.button_text, detection.selector
            )
            if key not in seen_keys:
                seen_keys.add(key)
                overlays.append(
                    overlay_cache.CachedOverlay(
                        overlay_type=(
                            detection.overlay_type
                            or "other"
                        ),
                        button_text=detection.button_text,
                        selector=detection.selector,
                        accessor_type=accessor,
                    )
                )

        if not overlays:
            overlay_cache.remove(self._domain)
            return

        entry = overlay_cache.OverlayCacheEntry(
            domain=self._domain,
            overlays=overlays,
        )
        overlay_cache.save(entry)


def _infer_accessor_type(
    detection: consent.CookieConsentDetection,
) -> overlay_cache.AccessorType:
    """Infer how the overlay element was located.

    Uses the detection fields to determine whether the
    element was found via CSS selector, button role, or
    text search.
    """
    if detection.selector:
        return "css-selector"
    if detection.button_text:
        return "button-role"
    return "text-search"


def _detection_signature(
    detection: consent.CookieConsentDetection,
) -> str:
    """Build a hashable key for a detection to track repeats."""
    return (
        f"{detection.selector or ''}|"
        f"{detection.button_text or ''}"
    )
