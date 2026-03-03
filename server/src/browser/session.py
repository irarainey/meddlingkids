"""Browser session management for concurrent analysis support.

Each ``BrowserSession`` wraps an isolated ``BrowserContext``
(like a fresh incognito window) that shares a single Chrome
instance managed by :class:`~src.browser.manager.PlaywrightManager`.

Creating a context per request is fast (~50 ms) and provides
full cookie/storage isolation without the overhead of starting
a new Chromium process per scan.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal, Self

from playwright import async_api

from src.browser import access_detection
from src.models import browser, tracking_data
from src.utils import image, logger
from src.utils import url as url_mod

log = logger.create_logger("BrowserSession")

# ============================================================================
# Constants
# ============================================================================

MAX_TRACKED_REQUESTS = 5000
MAX_TRACKED_SCRIPTS = 1000

# Per-operation timeout (seconds) for graceful context cleanup.
_CLOSE_TIMEOUT_SECONDS = 8

# Timeout (seconds) for data-capture calls (cookies, storage).
# These go through CDP to the renderer; on ad-heavy pages the
# browser can become unresponsive for tens of seconds.  A
# bounded timeout prevents Phase 4/5 from stalling the entire
# SSE stream.
_CAPTURE_TIMEOUT_SECONDS = 10

# File extensions that are not JavaScript and should be
# excluded even when the browser tags them as "script".
_NON_SCRIPT_EXTENSIONS = frozenset(
    {
        ".json",
        ".css",
        ".html",
        ".htm",
        ".xml",
        ".svg",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
    }
)


def _is_non_script_url(url: str) -> bool:
    """Return ``True`` when the URL path has a non-script extension.

    Strips query strings and fragments before checking so that
    URLs like ``data.json?callback=cb`` are correctly rejected.
    """
    # Strip query and fragment
    path = url.split("?", 1)[0].split("#", 1)[0]
    dot = path.rfind(".")
    if dot == -1:
        return False
    ext = path[dot:].lower()
    return ext in _NON_SCRIPT_EXTENSIONS


class BrowserSession:
    """Isolated session for a single URL analysis.

    Wraps a ``BrowserContext`` + ``Page`` created by
    :class:`~src.browser.manager.PlaywrightManager`.  Each
    session has its own cookies, storage, and tracking state.

    Use :meth:`bind_context` (called by the manager) to
    attach a context and page after construction.
    """

    def __init__(self) -> None:
        """Initialise a new browser session with empty state."""
        self._context: async_api.BrowserContext | None = None
        self._page: async_api.Page | None = None
        self._current_page_url: str = ""

        self._tracked_cookies: list[tracking_data.TrackedCookie] = []
        self._tracked_scripts: list[tracking_data.TrackedScript] = []
        self._tracked_network_requests: list[tracking_data.NetworkRequest] = []

        # O(1) lookup indexes for hot-path deduplication
        self._seen_script_urls: set[str] = set()
        self._cookie_index: dict[tuple[str, str], int] = {}
        self._pending_responses: dict[str, list[int]] = {}

    # ==========================================================================
    # State Getters
    # ==========================================================================

    def get_page(self) -> async_api.Page | None:
        """Return the active Playwright page, if any."""
        return self._page

    def get_tracked_cookies(self) -> list[tracking_data.TrackedCookie]:
        """Return all cookies captured during this session."""
        return self._tracked_cookies

    def get_tracked_scripts(self) -> list[tracking_data.TrackedScript]:
        """Return all scripts intercepted during this session."""
        return self._tracked_scripts

    def get_tracked_network_requests(self) -> list[tracking_data.NetworkRequest]:
        """Return all network requests captured during this session."""
        return self._tracked_network_requests

    # ==========================================================================
    # State Management
    # ==========================================================================

    def clear_tracking_data(self) -> None:
        """Clear all captured cookies, scripts, and requests."""
        self._tracked_cookies.clear()
        self._tracked_scripts.clear()
        self._tracked_network_requests.clear()
        self._seen_script_urls.clear()
        self._cookie_index.clear()
        self._pending_responses.clear()

    def set_current_page_url(self, url: str) -> None:
        """Set the URL used to classify first- vs third-party requests."""
        self._current_page_url = url

    # ==========================================================================
    # Context Binding (called by PlaywrightManager)
    # ==========================================================================

    def bind_context(
        self,
        context: async_api.BrowserContext,
        page: async_api.Page,
    ) -> None:
        """Attach a browser context and page to this session.

        Called by :meth:`PlaywrightManager.create_session` after
        creating the context with device emulation and anti-bot
        init scripts.  Registers the network request/response
        listeners needed for tracking.
        """
        self._context = context
        self._page = page
        page.on("request", self._on_request)
        page.on("response", self._on_response)

    def _on_request(self, request: async_api.Request) -> None:
        """Handle intercepted network requests."""
        try:
            self._on_request_inner(request)
        except Exception as exc:
            log.debug("Request handler error", {"error": str(exc)})

    def _on_request_inner(self, request: async_api.Request) -> None:
        """Inner request handler — separated so _on_request can guard exceptions."""
        resource_type = request.resource_type
        request_url = request.url
        domain = url_mod.extract_domain(request_url)

        # Track scripts — O(1) set lookup for deduplication.
        # Skip blob: URLs which are browser-internal inline
        # scripts that cannot be fetched or meaningfully
        # analysed.  Also skip non-script file extensions
        # (e.g. .json) that the browser may tag as "script"
        # when loaded via <script src="...">.
        if resource_type == "script" and not request_url.startswith("blob:") and not _is_non_script_url(request_url):
            if len(self._tracked_scripts) < MAX_TRACKED_SCRIPTS and request_url not in self._seen_script_urls:
                self._seen_script_urls.add(request_url)
                self._tracked_scripts.append(
                    tracking_data.TrackedScript(
                        url=request_url,
                        domain=domain,
                        timestamp=datetime.now(UTC).isoformat(),
                    )
                )
            elif len(self._tracked_scripts) == MAX_TRACKED_SCRIPTS:
                log.debug("Script tracking limit reached", {"limit": MAX_TRACKED_SCRIPTS})

        # Track ALL network requests (with limit)
        if len(self._tracked_network_requests) == MAX_TRACKED_REQUESTS:
            log.debug("Network request tracking limit reached", {"limit": MAX_TRACKED_REQUESTS})
        if len(self._tracked_network_requests) < MAX_TRACKED_REQUESTS:
            idx = len(self._tracked_network_requests)
            post_data: str | None = None
            if request.method.upper() == "POST":
                try:
                    post_data = request.post_data
                except Exception:
                    post_data = None
            # Derive the initiating domain from the request's
            # parent frame URL so we can visualise domain
            # relationships in the tracker graph.
            initiator_domain: str | None = None
            try:
                frame = request.frame
                if frame and frame.url:
                    initiator_domain = url_mod.extract_domain(
                        frame.url,
                    )
            except Exception:
                initiator_domain = None

            redirected_from_url: str | None = None
            try:
                prev = request.redirected_from
                if prev:
                    redirected_from_url = prev.url
            except Exception:
                redirected_from_url = None

            self._tracked_network_requests.append(
                tracking_data.NetworkRequest(
                    url=request_url,
                    domain=domain,
                    method=request.method,
                    resource_type=resource_type,
                    is_third_party=url_mod.is_third_party(
                        request_url,
                        self._current_page_url,
                    ),
                    timestamp=datetime.now(UTC).isoformat(),
                    post_data=post_data,
                    initiator_domain=initiator_domain,
                    redirected_from_url=redirected_from_url,
                )
            )
            # Index for O(1) response matching
            self._pending_responses.setdefault(request_url, []).append(idx)

    def _on_response(self, response: async_api.Response) -> None:
        """Handle intercepted responses to capture status codes."""
        try:
            request_url = response.url
            indices = self._pending_responses.get(request_url)
            if indices:
                idx = indices.pop()
                self._tracked_network_requests[idx].status_code = response.status
                if not indices:
                    del self._pending_responses[request_url]
        except Exception as exc:
            log.debug("Response handler error", {"error": str(exc)})

    # ==========================================================================
    # Navigation
    # ==========================================================================

    async def navigate_to(
        self,
        url: str,
        wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "networkidle",
        timeout: int = 90000,
    ) -> browser.NavigationResult:
        """Navigate the current page to a URL and wait for it to load."""
        if not self._page:
            raise RuntimeError("No browser session active")

        log.debug("Navigating", {"url": url, "waitUntil": wait_until, "timeout": timeout})
        try:
            response = await self._page.goto(
                url,
                wait_until=wait_until,
                timeout=timeout,
            )

            status_code = response.status if response else None
            status_text = response.status_text if response else None

            if status_code and status_code >= 400:
                # 402 (Payment Required) is used by paywall
                # sites like the Daily Telegraph.  The page
                # still renders fully — the paywall is enforced
                # client-side via an overlay — so we treat it
                # as a soft success and let the overlay pipeline
                # handle dismissal.
                if status_code == 402:
                    log.info(
                        "Paywall detected (HTTP 402) — proceeding with analysis",
                        {"statusCode": status_code},
                    )
                else:
                    is_access_denied = status_code in (401, 403)
                    return browser.NavigationResult(
                        success=False,
                        status_code=status_code,
                        status_text=status_text,
                        is_access_denied=is_access_denied,
                        error_message=(
                            f"Access denied ({status_code})" if is_access_denied else f"Server error ({status_code}: {status_text})"
                        ),
                    )

            final_url = self._page.url
            if final_url != url:
                log.info("Redirected", {"from": url, "to": final_url})
            return browser.NavigationResult(
                success=True,
                status_code=status_code,
                status_text=status_text,
                is_access_denied=False,
                error_message=None,
            )
        except Exception as error:
            log.warn("Navigation error", {"url": url, "error": str(error)})
            return browser.NavigationResult(
                success=False,
                status_code=None,
                status_text=None,
                is_access_denied=False,
                error_message=str(error),
            )

    async def wait_for_network_idle(self, timeout: int = 60000) -> bool:
        """Wait for the network to become idle."""
        if not self._page:
            return False
        try:
            await self._page.wait_for_load_state("networkidle", timeout=timeout)
            return True
        except Exception:
            log.debug("Network idle timeout", {"timeoutMs": timeout})
            return False

    async def check_for_access_denied(self) -> browser.AccessDenialResult:
        """Check if the current page indicates access denial."""
        if not self._page:
            return browser.AccessDenialResult(denied=False, reason=None)
        return await access_detection.check_for_access_denied(self._page)

    # ==========================================================================
    # Data Capture
    # ==========================================================================

    async def capture_current_cookies(self) -> None:
        """Capture all cookies from the current browser context.

        Wrapped in a timeout so an unresponsive browser doesn't
        stall the pipeline indefinitely.
        """
        if not self._context:
            return

        try:
            cookies = await asyncio.wait_for(
                self._context.cookies(),
                timeout=_CAPTURE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            log.warn(
                "Cookie capture timed out — browser may be unresponsive",
                {"timeoutSeconds": _CAPTURE_TIMEOUT_SECONDS},
            )
            return

        log.debug("Captured raw cookies from browser", {"count": len(cookies)})
        now = datetime.now(UTC).isoformat()

        for cookie in cookies:
            name = cookie.get("name", "")
            domain = cookie.get("domain", "")

            tracked = tracking_data.TrackedCookie(
                name=name,
                value=cookie.get("value", ""),
                domain=domain,
                path=cookie.get("path", "/"),
                expires=cookie.get("expires", -1),
                http_only=cookie.get("httpOnly", False),
                secure=cookie.get("secure", False),
                same_site=cookie.get("sameSite", "None"),
                timestamp=now,
            )

            cookie_key = (name, domain)
            existing_idx = self._cookie_index.get(cookie_key)
            if existing_idx is not None:
                self._tracked_cookies[existing_idx] = tracked
            else:
                self._cookie_index[cookie_key] = len(self._tracked_cookies)
                self._tracked_cookies.append(tracked)

    async def capture_storage(self) -> tracking_data.CapturedStorage:
        """Capture localStorage and sessionStorage contents.

        Wrapped in a timeout so an unresponsive browser doesn't
        stall the pipeline indefinitely.
        """
        if not self._page:
            return tracking_data.CapturedStorage()

        try:
            storage_data = await asyncio.wait_for(
                self._page.evaluate(
                    """() => {
                        const getItems = (s) => {
                            const items = [];
                            for (let i = 0; i < s.length; i++) {
                                const key = s.key(i);
                                if (key) items.push({ key, value: s.getItem(key) || '' });
                            }
                            return items;
                        };
                        return {
                            localStorage: getItems(window.localStorage),
                            sessionStorage: getItems(window.sessionStorage),
                        };
                    }"""
                ),
                timeout=_CAPTURE_TIMEOUT_SECONDS,
            )

            now = datetime.now(UTC).isoformat()
            return tracking_data.CapturedStorage(
                local_storage=[
                    tracking_data.StorageItem(key=item["key"], value=item["value"], timestamp=now) for item in storage_data["localStorage"]
                ],
                session_storage=[
                    tracking_data.StorageItem(key=item["key"], value=item["value"], timestamp=now)
                    for item in storage_data["sessionStorage"]
                ],
            )
        except TimeoutError:
            log.warn(
                "Storage capture timed out — browser may be unresponsive",
                {"timeoutSeconds": _CAPTURE_TIMEOUT_SECONDS},
            )
            return tracking_data.CapturedStorage()
        except Exception as exc:
            log.warn("Failed to capture storage", {"error": str(exc)})
            return tracking_data.CapturedStorage()

    async def take_screenshot(self, full_page: bool = False, *, timeout: int = 15_000) -> bytes:
        """Take a JPEG screenshot of the current page.

        Captures directly as JPEG (quality 72) so no further
        format conversion is needed — all downstream consumers
        (client display, LLM vision) use the bytes as-is or
        downscale for the vision API.

        Args:
            full_page: Capture the full scrollable page instead of just
                the viewport.
            timeout: Maximum time in milliseconds to wait for the
                screenshot.  Defaults to 15 000 ms.
        """
        if not self._page:
            raise RuntimeError("No browser session active")
        return await self._page.screenshot(
            type="jpeg",
            quality=72,
            full_page=full_page,
            timeout=timeout,
        )

    @staticmethod
    def optimize_screenshot_bytes(screenshot_bytes: bytes) -> str:
        """Convert raw screenshot bytes to an optimized JPEG data URL.

        Downscales wide images for smaller payloads.  This is a
        pure CPU operation — no browser round-trip.

        Returns an empty string when *screenshot_bytes* is empty so
        callers that fall back to ``b""`` on screenshot failure still
        produce a valid (blank) event payload.
        """
        if not screenshot_bytes:
            return ""
        return image.screenshot_to_data_url(screenshot_bytes)

    async def get_page_content(self) -> str:
        """Get the full HTML content of the current page.

        Wrapped in a timeout so an unresponsive browser
        (e.g. overwhelmed by ad-heavy pages) doesn't stall
        the pipeline indefinitely.
        """
        if not self._page:
            raise RuntimeError("No browser session active")
        try:
            return await asyncio.wait_for(
                self._page.content(),
                timeout=_CAPTURE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            log.warn(
                "Page content capture timed out — browser may be unresponsive",
                {"timeoutSeconds": _CAPTURE_TIMEOUT_SECONDS},
            )
            return ""

    # ==========================================================================
    # Page Interaction Helpers
    # ==========================================================================

    async def wait_for_timeout(self, ms: int) -> None:
        """Wait for a specified number of milliseconds.

        Uses ``asyncio.sleep`` instead of Playwright's
        ``page.wait_for_timeout`` which is intended only
        for debugging and should not be used in production.
        """
        await asyncio.sleep(ms / 1000)

    async def wait_for_load_state(
        self,
        state: Literal["domcontentloaded", "load", "networkidle"] = "load",
        *,
        timeout: int = 30_000,
    ) -> bool:
        """Wait for a specific page load state.

        Args:
            state: The load state to wait for.
            timeout: Maximum wait in milliseconds.  Defaults to
                30 000 ms.  Pass ``0`` to disable.

        Returns:
            ``True`` if the state was reached, ``False`` on timeout.
        """
        if not self._page:
            raise RuntimeError("No browser session active")
        try:
            await self._page.wait_for_load_state(
                state,
                timeout=timeout if timeout > 0 else None,
            )
            return True
        except Exception:
            log.debug(
                "Load state wait timed out",
                {"state": state, "timeoutMs": timeout},
            )
            return False

    # ==========================================================================
    # Cleanup
    # ==========================================================================

    async def __aenter__(self) -> Self:
        """Enter the async context manager (no-op; launch separately)."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Ensure session resources are released on exit."""
        await self.close()

    async def close(self) -> None:
        """Close the browser context for this session.

        Only tears down the per-request context — the shared
        Chrome browser remains running for future requests.
        Context close is fast (~50 ms) compared to shutting
        down the entire browser (~8 s).
        """
        log.debug("Closing browser session")

        if self._page:
            self._page.remove_listener("request", self._on_request)
            self._page.remove_listener(
                "response",
                self._on_response,
            )
            self._page = None

        if self._context:
            try:
                await asyncio.wait_for(
                    self._context.close(),
                    timeout=_CLOSE_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                log.warn(
                    "Context close timed out",
                    {"timeoutSeconds": _CLOSE_TIMEOUT_SECONDS},
                )
            except (asyncio.CancelledError, Exception):
                # Starlette cancel-scopes and task teardown can
                # interrupt the close — non-fatal because the
                # shared browser remains and the context will be
                # garbage-collected.
                pass
            self._context = None

        self.clear_tracking_data()
        log.debug("Browser session closed")
