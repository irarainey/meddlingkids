"""
Browser session management for concurrent analysis support.
Each BrowserSession instance manages its own isolated browser state,
allowing multiple concurrent URL analyses without interference.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Literal

from playwright import async_api
from src.browser import access_detection, device_configs
from src.models import browser, tracking_data
from src.utils import image
from src.utils import logger, url as url_mod

log = logger.create_logger("BrowserSession")

# ============================================================================
# Constants
# ============================================================================

MAX_TRACKED_REQUESTS = 5000
MAX_TRACKED_SCRIPTS = 1000


class BrowserSession:
    """
    Manages an isolated browser session for a single URL analysis.
    """

    def __init__(self) -> None:
        """Initialise a new browser session with empty state."""
        self._playwright: async_api.Playwright | None = None
        self._browser: async_api.Browser | None = None
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
    # Browser Lifecycle
    # ==========================================================================

    async def launch_browser(
        self, device_type: browser.DeviceType = "ipad"
    ) -> None:
        """Launch a new Chromium browser instance with device emulation."""
        # Ensure virtual display is available for headed mode.
        if not os.environ.get("DISPLAY") or os.environ.get("DISPLAY") in (":0", ":1"):
            os.environ["DISPLAY"] = os.environ.get("XVFB_DISPLAY", ":99")

        log.info("Launching browser", {"deviceType": device_type})
        if device_type not in device_configs.DEVICE_CONFIGS:
            raise ValueError(
                f"Unknown device type {device_type!r}. "
                f"Valid types: {', '.join(device_configs.DEVICE_CONFIGS)}"
            )
        device_config = device_configs.DEVICE_CONFIGS[device_type]

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

        pw = await async_api.async_playwright().start()
        self._playwright = pw

        # Prefer real Chrome over Playwright's bundled Chromium.
        # Real Chrome has genuine TLS fingerprints (JA3/JA4)
        # that CDN-level bot detectors like Tollbit trust,
        # whereas bundled Chromium has a distinct fingerprint
        # that is trivially identified as automated.
        #
        # Install real Chrome via: playwright install chrome
        # Falls back to bundled Chromium if Chrome is not
        # available.
        launch_kwargs: dict[str, object] = {
            "headless": False,
            "args": [
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-extensions",
            ],
        }

        try:
            br = await pw.chromium.launch(
                channel="chrome", **launch_kwargs  # type: ignore[arg-type]
            )
            log.info("Launched real Chrome browser")
        except Exception:
            log.info(
                "Real Chrome not available, falling"
                " back to bundled Chromium"
            )
            br = await pw.chromium.launch(
                **launch_kwargs  # type: ignore[arg-type]
            )
        self._browser = br

        # Do NOT override user_agent here.  When using real
        # Chrome (channel="chrome"), the browser generates its
        # own UA string that matches its TLS fingerprint.  A
        # mismatched UA (e.g. Safari on iPad) vs Chrome TLS
        # handshake is a top bot-detection signal.
        self._context = await br.new_context(
            viewport={"width": device_config.viewport.width, "height": device_config.viewport.height},
            device_scale_factor=device_config.device_scale_factor,
            is_mobile=device_config.is_mobile,
            has_touch=device_config.has_touch,
            locale="en-GB",
            timezone_id="Europe/London",
            java_script_enabled=True,
        )

        self._page = await self._context.new_page()
        log.debug("Browser launched", {
            "viewport": f"{device_config.viewport.width}x{device_config.viewport.height}",
            "deviceType": device_type,
            "isMobile": device_config.is_mobile,
        })

        # ── Anti-bot-detection hardening ─────────────────
        # Mask automation signals that paywall and bot-detection
        # services (e.g. Piano / Arkose on telegraph.co.uk)
        # use to fingerprint Playwright/headless browsers.
        await self._context.add_init_script("""
            // 1. Remove webdriver flag
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

            // 2. Fake plugins array (headless has zero)
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                    { name: 'Native Client', filename: 'internal-nacl-plugin' },
                ],
            });

            // 3. Fake languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-GB', 'en-US', 'en'],
            });

            // 4. Permissions API — deny 'notifications' query
            //    (bot detectors probe this; real browsers return 'prompt')
            const originalQuery = window.navigator.permissions?.query;
            if (originalQuery) {
                window.navigator.permissions.query = (params) =>
                    params.name === 'notifications'
                        ? Promise.resolve({ state: Notification.permission })
                        : originalQuery.call(window.navigator.permissions, params);
            }

            // 5. Ensure window.chrome exists (Chromium-specific)
            if (!window.chrome) {
                window.chrome = { runtime: {} };
            }

            // 6. Spoof WebGL renderer to mask headless GPU
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function (param) {
                if (param === 37445) return 'Google Inc. (Intel)';
                if (param === 37446) return 'ANGLE (Intel, Mesa Intel(R) UHD Graphics, OpenGL 4.6)';
                return getParameter.call(this, param);
            };

            // 7. Spoof AudioContext to produce stable,
            //    realistic fingerprints (bot detectors hash
            //    the output of an OfflineAudioContext render
            //    to identify headless/virtual environments).
            const origGetFloatFreqData =
                AnalyserNode.prototype.getFloatFrequencyData;
            AnalyserNode.prototype.getFloatFrequencyData = function (arr) {
                origGetFloatFreqData.call(this, arr);
                // Inject tiny noise so the hash looks organic
                for (let i = 0; i < arr.length; i++) {
                    arr[i] += 0.01 * (Math.random() - 0.5);
                }
            };

            // 8. MediaDevices — report a realistic set of
            //    media devices (camera + mic + speakers).
            //    Headless environments often report zero
            //    devices, which is a bot signal.
            if (navigator.mediaDevices?.enumerateDevices) {
                const origEnum = navigator.mediaDevices.enumerateDevices.bind(
                    navigator.mediaDevices,
                );
                navigator.mediaDevices.enumerateDevices = async () => {
                    const real = await origEnum();
                    if (real.length > 0) return real;
                    // Return plausible defaults when none exist
                    return [
                        { deviceId: 'default', kind: 'audioinput',  label: '', groupId: 'g1' },
                        { deviceId: 'default', kind: 'audiooutput', label: '', groupId: 'g1' },
                        { deviceId: 'default', kind: 'videoinput',  label: '', groupId: 'g2' },
                    ];
                };
            }
        """)

        # Set up request tracking
        self._page.on("request", self._on_request)
        self._page.on("response", self._on_response)

    def _on_request(self, request: async_api.Request) -> None:
        """Handle intercepted network requests."""
        resource_type = request.resource_type
        request_url = request.url
        domain = url_mod.extract_domain(request_url)

        # Track scripts — O(1) set lookup for deduplication.
        # Skip blob: URLs which are browser-internal inline
        # scripts that cannot be fetched or meaningfully
        # analysed.
        if resource_type == "script" and not request_url.startswith("blob:"):
            if (
                len(self._tracked_scripts) < MAX_TRACKED_SCRIPTS
                and request_url not in self._seen_script_urls
            ):
                self._seen_script_urls.add(request_url)
                self._tracked_scripts.append(
                    tracking_data.TrackedScript(
                        url=request_url,
                        domain=domain,
                        timestamp=datetime.now(
                            timezone.utc
                        ).isoformat(),
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
                    timestamp=datetime.now(
                        timezone.utc
                    ).isoformat(),
                    post_data=post_data,
                )
            )
            # Index for O(1) response matching
            self._pending_responses.setdefault(
                request_url, []
            ).append(idx)

    def _on_response(self, response: async_api.Response) -> None:
        """Handle intercepted responses to capture status codes."""
        request_url = response.url
        indices = self._pending_responses.get(request_url)
        if indices:
            idx = indices.pop()
            self._tracked_network_requests[idx].status_code = (
                response.status
            )
            if not indices:
                del self._pending_responses[request_url]

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
                        "Paywall detected (HTTP 402)"
                        " — proceeding with analysis",
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
                            f"Access denied ({status_code})"
                            if is_access_denied
                            else f"Server error ({status_code}: {status_text})"
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
        """Capture all cookies from the current browser context."""
        if not self._context:
            return

        cookies = await self._context.cookies()
        log.debug("Captured raw cookies from browser", {"count": len(cookies)})
        now = datetime.now(timezone.utc).isoformat()

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
                self._cookie_index[cookie_key] = len(
                    self._tracked_cookies
                )
                self._tracked_cookies.append(tracked)

    async def capture_storage(self) -> dict[str, list[tracking_data.StorageItem]]:
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
                    tracking_data.StorageItem(key=item["key"], value=item["value"], timestamp=now)
                    for item in storage_data["localStorage"]
                ],
                "session_storage": [
                    tracking_data.StorageItem(key=item["key"], value=item["value"], timestamp=now)
                    for item in storage_data["sessionStorage"]
                ],
            }
        except Exception as exc:
            log.warn("Failed to capture storage", {"error": str(exc)})
            return {"local_storage": [], "session_storage": []}

    async def take_screenshot(self, full_page: bool = False) -> bytes:
        """Take a PNG screenshot of the current page (for AI analysis)."""
        if not self._page:
            raise RuntimeError("No browser session active")
        return await self._page.screenshot(type="png", full_page=full_page)

    @staticmethod
    def optimize_screenshot_bytes(png_bytes: bytes) -> str:
        """Convert raw PNG screenshot bytes to an optimized JPEG data URL.

        Downscales wide images and compresses to JPEG for smaller
        payloads.  This is a pure CPU operation — no browser round-trip.
        """
        return image.png_to_data_url(png_bytes)

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
        log.debug("Closing browser session")
        if self._page:
            self._page.remove_listener("request", self._on_request)
            self._page.remove_listener("response", self._on_response)
            self._page = None

        if self._context:
            try:
                await self._context.close()
            except Exception as exc:
                log.debug("Context close error (non-fatal)", {"error": str(exc)})
            self._context = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception as exc:
                log.debug("Browser close error (non-fatal)", {"error": str(exc)})
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as exc:
                log.debug("Playwright stop error (non-fatal)", {"error": str(exc)})
            self._playwright = None

        self.clear_tracking_data()
        log.debug("Browser session closed")
