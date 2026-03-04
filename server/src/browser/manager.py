"""
Shared Playwright and browser lifecycle management.

Starts a single Playwright server process and Chrome browser at
application startup (via FastAPI lifespan), then reuses them
across all analysis requests.  Each request gets an isolated
``BrowserContext`` (like a fresh incognito window) that is cheap
to create (~50 ms) and destroy, rather than spawning a full
Chromium + Playwright node process per request (~4–9 s).

This eliminates:
- progressive slowdown from orphaned node/Chrome processes
- 4–20 s startup overhead per scan
- resource exhaustion when cleanup in async generator ``finally``
  blocks doesn't reliably complete under Starlette's response
  lifecycle

The ``PlaywrightManager`` auto-recovers when Chrome crashes:
``_ensure_browser()`` checks ``browser.is_connected()`` and
restarts if needed before creating a new session.
"""

from __future__ import annotations

import asyncio
import os
import signal

from playwright import async_api

from src.browser import device_configs
from src.browser import session as session_mod
from src.models import browser
from src.utils import logger

log = logger.create_logger("PlaywrightManager")

# Per-operation timeout (seconds) for graceful shutdown of the
# shared browser and Playwright server.
_STOP_TIMEOUT_SECONDS = 8

# Timeout (seconds) for Playwright startup.
_START_TIMEOUT_SECONDS = 15

# Maximum attempts to start the browser (covers transient Xvfb
# or display-server issues in containers).
_MAX_START_ATTEMPTS = 2

# Delay between restart attempts (seconds).
_RESTART_DELAY_SECONDS = 2

# Timeout (seconds) for the health-check probe that verifies
# the browser can still create contexts after a suspected hang.
_HEALTH_CHECK_TIMEOUT_SECONDS = 10

# Timeout (seconds) for the full create_session operation so a
# truly hung browser can never block the server indefinitely.
_CREATE_SESSION_TIMEOUT_SECONDS = 30

# ── Anti-bot-detection init script ──────────────────────────
# Injected into every BrowserContext so all frames mask
# automation signals before any site scripts run.
_ANTI_BOT_INIT_SCRIPT = """
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

    // 7. Spoof AudioContext fingerprints
    const origGetFloatFreqData =
        AnalyserNode.prototype.getFloatFrequencyData;
    AnalyserNode.prototype.getFloatFrequencyData = function (arr) {
        origGetFloatFreqData.call(this, arr);
        for (let i = 0; i < arr.length; i++) {
            arr[i] += 0.01 * (Math.random() - 0.5);
        }
    };

    // 8. MediaDevices — report realistic devices
    if (navigator.mediaDevices?.enumerateDevices) {
        const origEnum = navigator.mediaDevices.enumerateDevices.bind(
            navigator.mediaDevices,
        );
        navigator.mediaDevices.enumerateDevices = async () => {
            const real = await origEnum();
            if (real.length > 0) return real;
            return [
                { deviceId: 'default', kind: 'audioinput',  label: '', groupId: 'g1' },
                { deviceId: 'default', kind: 'audiooutput', label: '', groupId: 'g1' },
                { deviceId: 'default', kind: 'videoinput',  label: '', groupId: 'g2' },
            ];
        };
    }
"""


class PlaywrightManager:
    """Manages a single shared Playwright + Chrome instance.

    Call ``start()`` once at application startup and ``stop()``
    at shutdown.  Use ``create_session()`` to get an isolated
    ``BrowserSession`` per analysis request.
    """

    _instance: PlaywrightManager | None = None

    def __init__(self) -> None:
        self._playwright: async_api.Playwright | None = None
        self._browser: async_api.Browser | None = None
        self._browser_pid: int | None = None
        self._lock = asyncio.Lock()
        self._started = False
        self._health_suspect = False

    # ── Singleton access ────────────────────────────────────

    @classmethod
    def get_instance(cls) -> PlaywrightManager:
        """Return the singleton manager instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Discard the singleton (for tests only)."""
        cls._instance = None

    # ── Lifecycle ───────────────────────────────────────────

    async def start(self) -> None:
        """Start Playwright and launch Chrome.

        Safe to call multiple times — subsequent calls are no-ops
        when the browser is already running and connected.
        """
        async with self._lock:
            if self._started and self._browser and self._browser.is_connected():
                return
            await self._start_browser()

    async def _start_browser(self) -> None:
        """Internal browser startup (caller must hold ``_lock``).

        Retries up to ``_MAX_START_ATTEMPTS`` times with cleanup
        between attempts to handle transient failures (crashed
        display server, zombie processes, resource exhaustion).
        """
        last_error: Exception | None = None
        for attempt in range(1, _MAX_START_ATTEMPTS + 1):
            try:
                await self._start_single_attempt()
                self._started = True
                log.info(
                    "Shared browser ready",
                    {"pid": self._browser_pid, "attempt": attempt},
                )
                return
            except Exception as exc:
                last_error = exc
                if attempt < _MAX_START_ATTEMPTS:
                    log.warn(
                        "Browser start failed, retrying",
                        {"attempt": attempt, "error": str(exc)[:200]},
                    )
                    await self._stop_internal()
                    await asyncio.sleep(_RESTART_DELAY_SECONDS)
                else:
                    log.error(
                        "Browser start failed after all attempts",
                        {"attempts": _MAX_START_ATTEMPTS, "error": str(exc)[:200]},
                    )
        raise RuntimeError(f"Failed to start browser after {_MAX_START_ATTEMPTS} attempts: {last_error}")

    async def _start_single_attempt(self) -> None:
        """One attempt at starting Playwright + Chrome."""
        # Determine display for headed mode.
        display = os.environ.get("DISPLAY", "")
        if not display or display in (":0", ":1"):
            display = os.environ.get("XVFB_DISPLAY", ":99")

        try:
            pw = await asyncio.wait_for(
                async_api.async_playwright().start(),
                timeout=_START_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            raise RuntimeError(f"Playwright failed to start within {_START_TIMEOUT_SECONDS}s") from None
        self._playwright = pw

        # Only pass essential environment variables to the browser
        # process.  Avoid leaking API keys or other secrets from
        # the server environment.
        browser_env_allowlist = (
            "DISPLAY",
            "HOME",
            "PATH",
            "LD_LIBRARY_PATH",
            "XDG_RUNTIME_DIR",
            "DBUS_SESSION_BUS_ADDRESS",
            "FONTCONFIG_PATH",
            "TMPDIR",
        )
        launch_env: dict[str, str] = {k: os.environ[k] for k in browser_env_allowlist if k in os.environ}
        launch_env["DISPLAY"] = display
        launch_kwargs: dict[str, object] = {
            "headless": False,
            "args": [
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-extensions",
            ],
            "env": launch_env,
        }

        try:
            br = await pw.chromium.launch(
                channel="chrome",
                **launch_kwargs,  # type: ignore[arg-type]
            )
            log.info("Launched real Chrome browser")
        except Exception as exc:
            log.info(
                "Real Chrome not available, falling back to bundled Chromium",
                {"reason": str(exc)[:120]},
            )
            br = await pw.chromium.launch(
                **launch_kwargs,  # type: ignore[arg-type]
            )
        self._browser = br

        # Track browser PID for force-kill on shutdown.
        try:
            bproc = getattr(br, "_impl_obj", None)
            conn = getattr(bproc, "_connection", None)
            transport = getattr(conn, "_transport", None)
            server_proc = getattr(transport, "_proc", None)
            if server_proc and hasattr(server_proc, "pid"):
                self._browser_pid = server_proc.pid
        except Exception:
            self._browser_pid = None

    def mark_health_suspect(self) -> None:
        """Flag the shared browser as potentially unhealthy.

        Called by ``BrowserSession.close()`` when a context close
        times out, which suggests the browser process may be hung.
        The next call to ``_ensure_browser()`` will run a health
        probe before returning the existing instance.
        """
        if not self._health_suspect:
            self._health_suspect = True
            log.warn("Browser marked as health-suspect — will probe before next session")

    async def _ensure_browser(self) -> async_api.Browser:
        """Return the shared browser, restarting if it has crashed.

        Called by ``create_session`` before creating a new context.
        Thread-safe via ``_lock``.

        When ``_health_suspect`` is set (e.g. after a context close
        timed out), runs a lightweight probe that opens and closes
        a throwaway context within a timeout.  If the probe hangs
        or fails, the browser is torn down and restarted.
        """
        async with self._lock:
            needs_restart = False

            if self._browser is None or not self._browser.is_connected():
                log.warn("Shared browser disconnected — restarting")
                needs_restart = True
            elif self._health_suspect:
                log.info("Running browser health probe")
                if not await self._probe_browser_health():
                    log.warn("Browser health probe failed — restarting")
                    needs_restart = True
                else:
                    log.info("Browser health probe passed")
                self._health_suspect = False

            if needs_restart:
                self._health_suspect = False
                await self._stop_internal()
                await self._start_browser()

            assert self._browser is not None
            return self._browser

    async def _probe_browser_health(self) -> bool:
        """Open and close a throwaway context to verify responsiveness.

        Returns ``True`` when the browser responds within the
        timeout, ``False`` when it is hung or broken.
        Caller must hold ``_lock``.
        """
        if self._browser is None:
            return False
        try:
            ctx = await asyncio.wait_for(
                self._browser.new_context(),
                timeout=_HEALTH_CHECK_TIMEOUT_SECONDS,
            )
            await asyncio.wait_for(
                ctx.close(),
                timeout=_HEALTH_CHECK_TIMEOUT_SECONDS,
            )
            return True
        except Exception as exc:
            log.warn(
                "Health probe error",
                {"error": str(exc)[:200]},
            )
            return False

    # ── Session factory ─────────────────────────────────────

    async def create_session(
        self,
        device_type: browser.DeviceType = "ipad",
    ) -> session_mod.BrowserSession:
        """Create an isolated ``BrowserSession`` for one analysis.

        Each session gets its own ``BrowserContext`` (like a new
        incognito window) with device emulation and anti-bot
        init scripts.  Creating a context is fast (~50 ms)
        compared to launching a full browser (~4–9 s).

        The entire operation is wrapped in a hard timeout so a
        hung browser can never block the server indefinitely.
        If the timeout fires, the browser is marked as
        health-suspect and the error propagates to the caller
        for retry.

        Args:
            device_type: Device profile for viewport, scaling,
                and touch emulation.

        Returns:
            A ready-to-use ``BrowserSession`` with an active page.

        Raises:
            TimeoutError: If session creation takes longer than
                ``_CREATE_SESSION_TIMEOUT_SECONDS``.
        """
        try:
            return await asyncio.wait_for(
                self._create_session_internal(device_type),
                timeout=_CREATE_SESSION_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            log.error(
                "Session creation timed out — browser is likely unresponsive",
                {"timeoutSeconds": _CREATE_SESSION_TIMEOUT_SECONDS},
            )
            self.mark_health_suspect()
            raise

    async def _create_session_internal(
        self,
        device_type: browser.DeviceType,
    ) -> session_mod.BrowserSession:
        """Actual session creation logic (no outer timeout)."""
        if device_type not in device_configs.DEVICE_CONFIGS:
            raise ValueError(f"Unknown device type {device_type!r}. Valid types: {', '.join(device_configs.DEVICE_CONFIGS)}")
        device_config = device_configs.DEVICE_CONFIGS[device_type]
        br = await self._ensure_browser()

        context = await br.new_context(
            viewport={
                "width": device_config.viewport.width,
                "height": device_config.viewport.height,
            },
            device_scale_factor=device_config.device_scale_factor,
            is_mobile=device_config.is_mobile,
            has_touch=device_config.has_touch,
            locale="en-GB",
            timezone_id="Europe/London",
            java_script_enabled=True,
            user_agent=device_config.user_agent,
        )
        await context.add_init_script(_ANTI_BOT_INIT_SCRIPT)

        page = await context.new_page()

        session = session_mod.BrowserSession(manager=self)
        session.bind_context(context, page)

        log.debug(
            "Session created",
            {
                "viewport": f"{device_config.viewport.width}x{device_config.viewport.height}",
                "deviceType": device_type,
                "isMobile": device_config.is_mobile,
            },
        )
        return session

    # ── Shutdown ────────────────────────────────────────────

    async def stop(self) -> None:
        """Stop the shared browser and Playwright process.

        Called once at application shutdown.
        """
        async with self._lock:
            await self._stop_internal()
        log.info("Shared browser stopped")

    async def _stop_internal(self) -> None:
        """Internal shutdown (caller must hold ``_lock``)."""
        graceful_ok = True

        if self._browser:
            try:
                await asyncio.wait_for(
                    self._browser.close(),
                    timeout=_STOP_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                log.warn(
                    "Browser close timed out",
                    {"timeoutSeconds": _STOP_TIMEOUT_SECONDS},
                )
                graceful_ok = False
            except Exception as exc:
                log.debug(
                    "Browser close error (non-fatal)",
                    {"error": str(exc)},
                )
            self._browser = None

        if self._playwright:
            try:
                await asyncio.wait_for(
                    self._playwright.stop(),
                    timeout=_STOP_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                log.warn(
                    "Playwright stop timed out",
                    {"timeoutSeconds": _STOP_TIMEOUT_SECONDS},
                )
                graceful_ok = False
            except Exception as exc:
                log.debug(
                    "Playwright stop error (non-fatal)",
                    {"error": str(exc)},
                )
            self._playwright = None

        if not graceful_ok:
            self._force_kill_browser_process()

        self._browser_pid = None
        self._started = False

    def _force_kill_browser_process(self) -> None:
        """Kill the browser process tree as a last resort.

        When Chrome runs in its own process group we send
        SIGKILL to the entire group.  If Chrome shares the
        server's process group, we kill only the single PID
        to avoid terminating the server itself.
        """
        pid = self._browser_pid
        if not pid:
            log.debug("No browser PID available for force-kill")
            return

        try:
            browser_pgid = os.getpgid(pid)
            server_pgid = os.getpgid(os.getpid())
            if browser_pgid != server_pgid:
                os.killpg(browser_pgid, signal.SIGKILL)
                log.warn(
                    "Force-killed browser process group",
                    {"pid": pid, "pgid": browser_pgid},
                )
                return
        except (ProcessLookupError, PermissionError, OSError):
            pass

        try:
            os.kill(pid, signal.SIGKILL)
            log.warn("Force-killed browser process", {"pid": pid})
        except ProcessLookupError:
            log.debug("Browser process already exited", {"pid": pid})
        except OSError as exc:
            log.warn(
                "Failed to force-kill browser process",
                {"pid": pid, "error": str(exc)},
            )
