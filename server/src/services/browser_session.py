"""
Browser session management for concurrent analysis support.
Each BrowserSession instance manages its own isolated browser state,
allowing multiple concurrent URL analyses without interference.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
from datetime import datetime, timezone
from typing import Literal

from PIL import Image
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Request,
    Response,
    async_playwright,
)

from src.services.access_detection import check_for_access_denied
from src.services.device_configs import DEVICE_CONFIGS
from src.types.browser import AccessDenialResult, DeviceType, NavigationResult
from src.types.tracking_data import (
    NetworkRequest,
    StorageItem,
    TrackedCookie,
    TrackedScript,
)
from src.utils.url import extract_domain, is_third_party

# ============================================================================
# Constants
# ============================================================================

MAX_TRACKED_REQUESTS = 5000
MAX_TRACKED_SCRIPTS = 1000

# Ensure browser uses virtual display for headed mode
if not os.environ.get("DISPLAY") or os.environ.get("DISPLAY") in (":0", ":1"):
    os.environ["DISPLAY"] = os.environ.get("XVFB_DISPLAY", ":99")


class BrowserSession:
    """
    Manages an isolated browser session for a single URL analysis.
    """

    def __init__(self) -> None:
        """Initialise a new browser session with empty state."""
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._current_page_url: str = ""

        self._tracked_cookies: list[TrackedCookie] = []
        self._tracked_scripts: list[TrackedScript] = []
        self._tracked_network_requests: list[NetworkRequest] = []

    async def __aenter__(self) -> BrowserSession:
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit the async context manager, closing all resources."""
        await self.close()

    # ==========================================================================
    # State Getters
    # ==========================================================================

    def get_page(self) -> Page | None:
        """Return the active Playwright page, if any."""
        return self._page

    def get_tracked_cookies(self) -> list[TrackedCookie]:
        """Return all cookies captured during this session."""
        return self._tracked_cookies

    def get_tracked_scripts(self) -> list[TrackedScript]:
        """Return all scripts intercepted during this session."""
        return self._tracked_scripts

    def get_tracked_network_requests(self) -> list[NetworkRequest]:
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

    def set_current_page_url(self, url: str) -> None:
        """Set the URL used to classify first- vs third-party requests."""
        self._current_page_url = url

    # ==========================================================================
    # Browser Lifecycle
    # ==========================================================================

    async def launch_browser(
        self, device_type: DeviceType = "ipad"
    ) -> None:
        """Launch a new Chromium browser instance with device emulation."""
        if device_type not in DEVICE_CONFIGS:
            raise ValueError(
                f"Unknown device type {device_type!r}. "
                f"Valid types: {', '.join(DEVICE_CONFIGS)}"
            )
        device_config = DEVICE_CONFIGS[device_type]

        # Close existing resources
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._page = None

        self._playwright = await async_playwright().start()

        self._browser = await self._playwright.chromium.launch(
            headless=False,
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-extensions",
            ],
        )

        self._context = await self._browser.new_context(
            user_agent=device_config.user_agent,
            viewport={"width": device_config.viewport.width, "height": device_config.viewport.height},
            device_scale_factor=device_config.device_scale_factor,
            is_mobile=device_config.is_mobile,
            has_touch=device_config.has_touch,
            locale="en-GB",
            timezone_id="Europe/London",
            java_script_enabled=True,
        )

        self._page = await self._context.new_page()

        # Remove webdriver flag
        await self._context.add_init_script(
            """Object.defineProperty(navigator, 'webdriver', { get: () => undefined })"""
        )

        # Set up request tracking
        self._page.on("request", self._on_request)
        self._page.on("response", self._on_response)

    def _on_request(self, request: Request) -> None:
        """Handle intercepted network requests."""
        resource_type = request.resource_type
        request_url = request.url
        domain = extract_domain(request_url)

        # Track scripts (deduplicate by URL)
        if resource_type == "script":
            if len(self._tracked_scripts) < MAX_TRACKED_SCRIPTS and not any(
                s.url == request_url for s in self._tracked_scripts
            ):
                self._tracked_scripts.append(
                    TrackedScript(
                        url=request_url,
                        domain=domain,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                )

        # Track ALL network requests (with limit)
        if len(self._tracked_network_requests) < MAX_TRACKED_REQUESTS:
            self._tracked_network_requests.append(
                NetworkRequest(
                    url=request_url,
                    domain=domain,
                    method=request.method,
                    resource_type=resource_type,
                    is_third_party=is_third_party(
                        request_url,
                        self._current_page_url,
                    ),
                    timestamp=datetime.now(
                        timezone.utc
                    ).isoformat(),
                )
            )

    def _on_response(self, response: Response) -> None:
        """Handle intercepted responses to capture status codes."""
        request_url = response.url
        # Reverse iterate — the matching request is almost always
        # near the end of the list because responses arrive shortly
        # after the corresponding request is appended.
        for req in reversed(self._tracked_network_requests):
            if req.url == request_url and req.status_code is None:
                req.status_code = response.status
                break

    # ==========================================================================
    # Navigation
    # ==========================================================================

    async def navigate_to(
        self,
        url: str,
        wait_until: Literal[
            "commit", "domcontentloaded", "load", "networkidle"
        ] = "networkidle",
        timeout: int = 90000,
    ) -> NavigationResult:
        """Navigate the current page to a URL and wait for it to load."""
        if not self._page:
            raise RuntimeError("No browser session active")

        try:
            response = await self._page.goto(url, wait_until=wait_until, timeout=timeout)

            status_code = response.status if response else None
            status_text = response.status_text if response else None

            if status_code and status_code >= 400:
                is_access_denied = status_code in (401, 403)
                return NavigationResult(
                    success=False,
                    status_code=status_code,
                    status_text=status_text,
                    is_access_denied=is_access_denied,
                    error_message=(
                        f"Access denied ({status_code})"
                        if is_access_denied
                        else f"Server error ({status_code}: {status_text})"
                    ),
                )

            return NavigationResult(
                success=True,
                status_code=status_code,
                status_text=status_text,
                is_access_denied=False,
                error_message=None,
            )
        except Exception as error:
            return NavigationResult(
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
            return False

    async def check_for_access_denied(self) -> AccessDenialResult:
        """Check if the current page indicates access denial."""
        if not self._page:
            return AccessDenialResult(denied=False, reason=None)
        return await check_for_access_denied(self._page)

    # ==========================================================================
    # Data Capture
    # ==========================================================================

    async def capture_current_cookies(self) -> None:
        """Capture all cookies from the current browser context."""
        if not self._context:
            return

        cookies = await self._context.cookies()
        now = datetime.now(timezone.utc).isoformat()

        for cookie in cookies:
            name = cookie.get("name", "")
            domain = cookie.get("domain", "")

            existing_idx = next(
                (
                    i
                    for i, c in enumerate(self._tracked_cookies)
                    if c.name == name and c.domain == domain
                ),
                None,
            )

            tracked = TrackedCookie(
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

            if existing_idx is not None:
                self._tracked_cookies[existing_idx] = tracked
            else:
                self._tracked_cookies.append(tracked)

    async def capture_storage(self) -> dict[str, list[StorageItem]]:
        """Capture localStorage and sessionStorage contents."""
        if not self._page:
            return {"local_storage": [], "session_storage": []}

        try:
            storage_data = await self._page.evaluate(
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
            )

            now = datetime.now(timezone.utc).isoformat()
            return {
                "local_storage": [
                    StorageItem(key=item["key"], value=item["value"], timestamp=now)
                    for item in storage_data["localStorage"]
                ],
                "session_storage": [
                    StorageItem(key=item["key"], value=item["value"], timestamp=now)
                    for item in storage_data["sessionStorage"]
                ],
            }
        except Exception:
            return {"local_storage": [], "session_storage": []}

    async def take_screenshot(self, full_page: bool = False) -> bytes:
        """Take a PNG screenshot of the current page (for AI analysis)."""
        if not self._page:
            raise RuntimeError("No browser session active")
        return await self._page.screenshot(type="png", full_page=full_page)

    async def take_optimized_screenshot(self, full_page: bool = False) -> str:
        """
        Take a JPEG screenshot optimized for client display.

        Returns a base64 data URL string ready for embedding.
        Uses JPEG compression and downscaling for smaller payloads.
        """
        if not self._page:
            raise RuntimeError("No browser session active")

        png_bytes = await self._page.screenshot(type="png", full_page=full_page)
        img = Image.open(io.BytesIO(png_bytes))

        # Downscale if wider than 1280px to reduce payload
        max_width = 1280
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize(
                (max_width, int(img.height * ratio)),
                Image.Resampling.LANCZOS,
            )

        # Convert to RGB (JPEG doesn't support alpha)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=72, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"

    async def get_page_content(self) -> str:
        """Get the full HTML content of the current page."""
        if not self._page:
            raise RuntimeError("No browser session active")
        return await self._page.content()

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
        state: Literal[
            "domcontentloaded", "load", "networkidle"
        ] = "load",
    ) -> None:
        """Wait for a specific page load state."""
        if not self._page:
            raise RuntimeError("No browser session active")
        await self._page.wait_for_load_state(state)

    # ==========================================================================
    # Cleanup
    # ==========================================================================

    async def close(self) -> None:
        """Close the browser and clean up all resources."""
        if self._page:
            self._page.remove_listener("request", self._on_request)
            self._page.remove_listener("response", self._on_response)
            self._page = None

        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        self.clear_tracking_data()

    def is_active(self) -> bool:
        """Check if a browser session is currently active."""
        return self._browser is not None and self._page is not None
