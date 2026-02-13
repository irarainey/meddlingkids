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
from typing import AsyncGenerator

import pydantic
from playwright import async_api
from src.browser import session as browser_session
from src.consent import overlay_cache
from src.models import consent, tracking_data
from src.pipeline import overlay_steps, sse_helpers
from src.utils import logger

log = logger.create_logger("Overlays")

MAX_OVERLAYS = 5

# Accept-style button text patterns.  When a cached overlay
# uses one of these, we try to find a reject/decline
# alternative first so the tool preserves user privacy.
_ACCEPT_BUTTON_RE = re.compile(
    r"accept|agree|allow|got it|i understand|okay"
    r"|ok\b|continue|confirm",
    re.IGNORECASE,
)

# Reject-style label regex used to locate a better button.
_REJECT_BUTTON_RE = re.compile(
    r"reject|decline|deny|refuse",
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
# Reject-button helper
# ====================================================================


async def _find_reject_button(
    frame: async_api.Frame,
) -> str | None:
    """Search *frame* for a reject/decline button.

    Returns the accessible name of the first matching button,
    or ``None`` if none was found.
    """
    try:
        locator = frame.get_by_role(
            "button", name=_REJECT_BUTTON_RE
        )
        if await locator.count() > 0:
            # Prefer the button whose text contains "all"
            # (e.g. "Reject all") for a more complete opt-out.
            for i in range(await locator.count()):
                text = (
                    await locator.nth(i).inner_text()
                )
                if text and "all" in text.lower():
                    return text.strip()
            # Fall back to the first match.
            text = await locator.first.inner_text()
            return text.strip() if text else None
    except Exception:
        pass
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
        self._deferred_extraction: (
            tuple[bytes, str | None] | None
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
                    ext_screenshot, ext_text = (
                        self._deferred_extraction
                    )
                    self._deferred_extraction = None
                    pending_extract = asyncio.create_task(
                        overlay_steps.collect_extraction_events(
                            page,
                            ext_screenshot,
                            result,
                            pre_click_consent_text=ext_text,
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
                log.info("Processing consent dialog concurrently with overlay verification")
                yield sse_helpers.format_progress_event(
                    "consent-analyze",
                    "Processing consent dialog...",
                    68,
                )
            else:
                log.info("Checking for additional overlays after dismissal")
                yield sse_helpers.format_progress_event(
                    "overlays-verify",
                    "Checking for additional overlays...",
                    68,
                )

        while overlay_count < MAX_OVERLAYS:
            # ── Detect ──────────────────────────────────────
            # Run detection independently — don't block on
            # pending extraction so the loop can break early
            # when no more overlays are found.
            detection = await overlay_steps.detect_overlay(
                session, overlay_count
            )

            if not detection.found or (
                not detection.selector
                and not detection.button_text
            ):
                for event in overlay_steps.build_no_overlay_events(
                    overlay_count, detection.reason
                ):
                    yield event
                break

            # ── Check for repeated detection ────────────────
            sig = overlay_steps.detection_signature(detection)
            if sig in failed_signatures:
                log.warn(
                    "Skipping re-detected overlay that"
                    " already failed to click",
                    {
                        "selector": detection.selector,
                        "buttonText": detection.button_text,
                    },
                )
                for event in overlay_steps.build_no_overlay_events(
                    overlay_count,
                    "Overlay re-detected but click already"
                    " failed — stopping",
                ):
                    yield event
                break

            # ── Validate in DOM ─────────────────────────────
            found_in_frame = await overlay_steps.validate_overlay_in_dom(
                page, detection
            )
            if not found_in_frame:
                # For cookie-consent overlays, the dialog
                # container may be visible but buttons may
                # still be loading (iframe content).  Wait
                # and retry validation before giving up.
                if (
                    detection.overlay_type == "cookie-consent"
                    and overlay_count == 0
                ):
                    log.info(
                        "Cookie-consent detected but"
                        " button not in DOM — waiting"
                        " for dialog content to load"
                    )
                    for _retry in range(4):
                        await asyncio.sleep(1.5)
                        found_in_frame = (
                            await overlay_steps.validate_overlay_in_dom(
                                page, detection
                            )
                        )
                        if found_in_frame:
                            log.info(
                                "Consent button appeared"
                                " after retry",
                                {"retries": _retry + 1},
                            )
                            break
                if not found_in_frame:
                    for event in overlay_steps.build_no_overlay_events(
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
                overlay_steps.get_overlay_message(detection.overlay_type),
                progress_base,
            )
            result.dismissed_overlays.append(detection)

            is_first_cookie_consent = (
                detection.overlay_type == "cookie-consent"
                and not result.consent_details
            )

            # ── Expand dialog & capture pre-click state ─────
            # For cookie-consent overlays, try to click
            # "More Options" to expand hidden partner lists
            # and capture the DOM text while the dialog is
            # still visible.
            pre_click_screenshot: bytes | None = None
            pre_click_consent_text: str | None = None
            if is_first_cookie_consent:
                yield sse_helpers.format_progress_event(
                    f"overlay-{overlay_count}-expand",
                    "Expanding consent details...",
                    progress_base,
                )
                pre_click_consent_text, pre_click_screenshot = (
                    await overlay_steps.expand_consent_dialog(
                        page, session,
                    )
                )

            # ── Click ───────────────────────────────────────
            yield sse_helpers.format_progress_event(
                f"overlay-{overlay_count}-click",
                "Dismissing overlay...",
                progress_base + 1,
            )

            try:
                clicked = False
                async for event in overlay_steps.click_and_capture(
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

                    # Even though click failed, preserve
                    # any pre-click consent data (text +
                    # screenshot) so the report includes
                    # consent analysis.
                    if (
                        is_first_cookie_consent
                        and pre_click_screenshot
                    ):
                        log.info(
                            "Click failed but pre-click"
                            " consent data available"
                            " — preserving for analysis",
                            {
                                "textLength": len(
                                    pre_click_consent_text
                                    or ""
                                ),
                            },
                        )
                        pending_extract = asyncio.create_task(
                            overlay_steps.collect_extraction_events(
                                page,
                                pre_click_screenshot,
                                result,
                                pre_click_consent_text=(
                                    pre_click_consent_text
                                ),
                            )
                        )

                    event, msg = overlay_steps.build_click_failure(
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

                # Preserve pre-click consent data on error
                if (
                    is_first_cookie_consent
                    and pre_click_screenshot
                ):
                    log.info(
                        "Click errored but pre-click"
                        " consent data available"
                        " — preserving for analysis",
                    )
                    pending_extract = asyncio.create_task(
                        overlay_steps.collect_extraction_events(
                            page,
                            pre_click_screenshot,
                            result,
                            pre_click_consent_text=(
                                pre_click_consent_text
                            ),
                        )
                    )

                event, msg = overlay_steps.build_click_failure(
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
                    overlay_steps.collect_extraction_events(
                        page,
                        pre_click_screenshot,
                        result,
                        pre_click_consent_text=pre_click_consent_text,
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
        self._failed_cache_types.clear()
        self._deferred_extraction = None
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
            found_in_frame = await overlay_steps.validate_overlay_in_dom(
                page, detection
            )
            if not found_in_frame:
                # For cookie-consent overlays, the dialog
                # container may appear before its buttons
                # load (iframe content).  Wait and retry.
                if (
                    cached.overlay_type == "cookie-consent"
                    and dismissed == 0
                ):
                    log.info(
                        "Cached cookie-consent button"
                        " not in DOM — waiting for"
                        " dialog content to load"
                    )
                    for _retry in range(4):
                        await asyncio.sleep(1.5)
                        found_in_frame = (
                            await overlay_steps.validate_overlay_in_dom(
                                page, detection
                            )
                        )
                        if found_in_frame:
                            log.info(
                                "Cached consent button"
                                " appeared after retry",
                                {"retries": _retry + 1},
                            )
                            break
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

            # ── Prefer reject over cached accept ───────
            # The cache may store an "accept" button from a
            # previous run.  Try to find a reject/decline
            # alternative first.
            if (
                cached.overlay_type == "cookie-consent"
                and cached.button_text
                and _ACCEPT_BUTTON_RE.search(
                    cached.button_text
                )
            ):
                reject_alt = await _find_reject_button(
                    found_in_frame
                )
                if reject_alt:
                    log.info(
                        "Found reject button — overriding"
                        " cached accept",
                        {
                            "cachedButton": (
                                cached.button_text
                            ),
                            "rejectButton": reject_alt,
                        },
                    )
                    detection = consent.CookieConsentDetection(
                        found=True,
                        overlay_type="cookie-consent",
                        selector=None,
                        button_text=reject_alt,
                        confidence="high",
                        reason=(
                            "reject preferred over"
                            " cached accept"
                        ),
                    )
                    # Re-validate so found_in_frame points
                    # at the frame containing the reject
                    # button (usually the same frame).
                    alt_frame = (
                        await overlay_steps.validate_overlay_in_dom(
                            page, detection
                        )
                    )
                    if alt_frame:
                        found_in_frame = alt_frame
                    else:
                        # Reject button vanished between
                        # search and validation — fall back
                        # to the original cached accept.
                        log.info(
                            "Reject button not found on"
                            " re-validation — using"
                            " cached accept",
                        )
                        detection = (
                            consent.CookieConsentDetection(
                                found=True,
                                overlay_type=(
                                    cached.overlay_type  # type: ignore[arg-type]
                                ),
                                selector=cached.selector,
                                button_text=(
                                    cached.button_text
                                ),
                                confidence="high",
                                reason=(
                                    "from overlay cache"
                                ),
                            )
                        )

            overlay_number = (
                result.overlay_count + dismissed + 1
            )
            progress_base = 45 + (overlay_number * 5)

            log.info(
                f"Cached overlay {overlay_number}"
                " validated in DOM",
                {
                    "type": cached.overlay_type,
                    "buttonText": detection.button_text,
                    "accessorType": cached.accessor_type,
                },
            )

            yield sse_helpers.format_progress_event(
                f"overlay-{overlay_number}-found",
                overlay_steps.get_overlay_message(
                    cached.overlay_type
                ),
                progress_base,
            )

            is_first_cookie = (
                cached.overlay_type == "cookie-consent"
                and not result.consent_details
            )

            # ── Expand dialog & capture pre-click state ─────
            pre_click_screenshot: bytes | None = None
            pre_click_consent_text: str | None = None
            if is_first_cookie:
                yield sse_helpers.format_progress_event(
                    f"overlay-{overlay_number}-expand",
                    "Expanding consent details...",
                    progress_base,
                )
                pre_click_consent_text, pre_click_screenshot = (
                    await overlay_steps.expand_consent_dialog(
                        page, session,
                    )
                )

            yield sse_helpers.format_progress_event(
                f"overlay-{overlay_number}-click",
                "Dismissing overlay...",
                progress_base + 1,
            )

            # Attempt click — stream events in real-time
            click_ok = False
            try:
                async for event in overlay_steps.click_and_capture(
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
                result.dismissed_overlays.append(detection)
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
                        pre_click_consent_text,
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
                # Preserve pre-click consent data even
                # when the cached click fails so consent
                # analysis is still included in the report.
                if is_first_cookie and pre_click_screenshot:
                    log.info(
                        "Cached click failed but pre-click"
                        " consent data available"
                        " — preserving for analysis",
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
        """Merge and persist a cache entry."""
        new_overlays = [
            overlay_cache.CachedOverlay(
                overlay_type=(
                    d.overlay_type or "other"
                ),
                button_text=d.button_text,
                selector=d.selector,
                accessor_type=overlay_steps.infer_accessor_type(d),
            )
            for d in result.dismissed_overlays
        ]
        overlay_cache.merge_and_save(
            self._domain,
            previous_entry,
            new_overlays,
            self._failed_cache_types,
        )
