"""Tests for BrowserSession cleanup and PlaywrightManager lifecycle.

Validates that:
- BrowserSession.close() reliably releases the per-request context
- PlaywrightManager starts/stops the shared browser correctly
- PlaywrightManager auto-recovers when Chrome crashes
- PlaywrightManager force-kills on shutdown timeout
"""

from __future__ import annotations

import asyncio
import signal
from unittest import mock

import pytest

from src.browser import manager as manager_mod
from src.browser import session as session_mod

# ====================================================================
# BrowserSession.close()
# ====================================================================


class TestBrowserSessionClose:
    """Validates BrowserSession.close() cleanup behaviour."""

    @pytest.mark.asyncio()
    async def test_close_on_fresh_session_is_noop(self) -> None:
        """Closing a never-bound session must not raise."""
        session = session_mod.BrowserSession()
        await session.close()
        assert session._context is None
        assert session._page is None

    @pytest.mark.asyncio()
    async def test_close_removes_event_listeners(self) -> None:
        """Page event listeners must be removed before closing."""
        session = session_mod.BrowserSession()
        page = mock.AsyncMock()
        # remove_listener is synchronous in Playwright; use a plain Mock
        # so the call doesn't return an unawaited coroutine.
        page.remove_listener = mock.Mock()
        session._page = page

        await session.close()

        page.remove_listener.assert_any_call(
            "request",
            session._on_request,
        )
        page.remove_listener.assert_any_call(
            "response",
            session._on_response,
        )
        assert session._page is None

    @pytest.mark.asyncio()
    async def test_close_closes_context(self) -> None:
        """Close must shut down the context."""
        session = session_mod.BrowserSession()
        ctx = mock.AsyncMock()
        session._context = ctx

        await session.close()

        ctx.close.assert_awaited_once()
        assert session._context is None

    @pytest.mark.asyncio()
    async def test_close_handles_context_timeout(self) -> None:
        """If context.close() hangs, close must not block forever."""
        session = session_mod.BrowserSession()

        async def hang_forever() -> None:
            await asyncio.sleep(3600)

        ctx = mock.AsyncMock()
        ctx.close = hang_forever
        session._context = ctx

        # close() should complete within a reasonable time
        # (not hang for the full 3600s).
        await asyncio.wait_for(
            session.close(),
            timeout=session_mod._CLOSE_TIMEOUT_SECONDS + 5,
        )
        assert session._context is None

    @pytest.mark.asyncio()
    async def test_close_continues_after_context_error(
        self,
    ) -> None:
        """An exception in context.close() must not stop cleanup."""
        session = session_mod.BrowserSession()
        ctx = mock.AsyncMock()
        ctx.close.side_effect = RuntimeError("oops")
        session._context = ctx

        await session.close()

        assert session._context is None

    @pytest.mark.asyncio()
    async def test_close_suppresses_cancelled_error(
        self,
    ) -> None:
        """CancelledError during context.close() must not propagate.

        Starlette cancel-scopes send CancelledError (a BaseException)
        when the SSE connection closes.  The session must still finish
        cleanup without raising.
        """
        session = session_mod.BrowserSession()
        ctx = mock.AsyncMock()
        ctx.close.side_effect = asyncio.CancelledError()
        session._context = ctx

        await session.close()

        assert session._context is None

    @pytest.mark.asyncio()
    async def test_close_clears_tracking_data(self) -> None:
        """All tracking state must be cleared on close."""
        session = session_mod.BrowserSession()
        session._tracked_cookies.append(mock.MagicMock())
        session._tracked_scripts.append(mock.MagicMock())
        session._tracked_network_requests.append(
            mock.MagicMock(),
        )
        session._seen_script_urls.add("https://x.com/a.js")

        await session.close()

        assert len(session._tracked_cookies) == 0
        assert len(session._tracked_scripts) == 0
        assert len(session._tracked_network_requests) == 0
        assert len(session._seen_script_urls) == 0


class TestBrowserSessionContextManager:
    """Validates async context manager protocol."""

    @pytest.mark.asyncio()
    async def test_aexit_calls_close(self) -> None:
        """Exiting the context manager must call close()."""
        session = session_mod.BrowserSession()
        with mock.patch.object(
            session,
            "close",
            new_callable=mock.AsyncMock,
        ) as mock_close:
            async with session:
                pass
            mock_close.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_aexit_calls_close_on_exception(self) -> None:
        """close() must be called even when the body raises."""
        session = session_mod.BrowserSession()
        with mock.patch.object(
            session,
            "close",
            new_callable=mock.AsyncMock,
        ) as mock_close:
            with pytest.raises(ValueError, match="boom"):
                async with session:
                    raise ValueError("boom")
            mock_close.assert_awaited_once()


class TestBindContext:
    """Validates bind_context registers listeners correctly."""

    def test_bind_sets_context_and_page(self) -> None:
        """bind_context must store the context and page."""
        session = session_mod.BrowserSession()
        ctx = mock.MagicMock()
        page = mock.MagicMock()
        page.on = mock.Mock()

        session.bind_context(ctx, page)

        assert session._context is ctx
        assert session._page is page

    def test_bind_registers_listeners(self) -> None:
        """bind_context must register request/response listeners."""
        session = session_mod.BrowserSession()
        ctx = mock.MagicMock()
        page = mock.MagicMock()
        page.on = mock.Mock()

        session.bind_context(ctx, page)

        page.on.assert_any_call("request", session._on_request)
        page.on.assert_any_call("response", session._on_response)


# ====================================================================
# PlaywrightManager lifecycle
# ====================================================================


class TestPlaywrightManagerSingleton:
    """Validates singleton pattern."""

    def test_get_instance_returns_same_object(self) -> None:
        """Successive calls return the same instance."""
        manager_mod.PlaywrightManager.reset_instance()
        m1 = manager_mod.PlaywrightManager.get_instance()
        m2 = manager_mod.PlaywrightManager.get_instance()
        assert m1 is m2
        manager_mod.PlaywrightManager.reset_instance()

    def test_reset_instance_clears_singleton(self) -> None:
        """reset_instance creates a fresh object on next call."""
        manager_mod.PlaywrightManager.reset_instance()
        m1 = manager_mod.PlaywrightManager.get_instance()
        manager_mod.PlaywrightManager.reset_instance()
        m2 = manager_mod.PlaywrightManager.get_instance()
        assert m1 is not m2
        manager_mod.PlaywrightManager.reset_instance()


class TestPlaywrightManagerStop:
    """Validates stop() safely shuts down browser + Playwright."""

    @pytest.mark.asyncio()
    async def test_stop_closes_browser_and_playwright(self) -> None:
        """stop() must close both browser and Playwright."""
        mgr = manager_mod.PlaywrightManager()
        br = mock.AsyncMock()
        br.is_connected.return_value = True
        pw = mock.AsyncMock()
        mgr._browser = br
        mgr._playwright = pw
        mgr._started = True

        await mgr.stop()

        br.close.assert_awaited_once()
        pw.stop.assert_awaited_once()
        assert mgr._browser is None
        assert mgr._playwright is None

    @pytest.mark.asyncio()
    async def test_stop_on_fresh_manager_is_noop(self) -> None:
        """Stopping a never-started manager must not raise."""
        mgr = manager_mod.PlaywrightManager()
        await mgr.stop()
        assert mgr._browser is None

    @pytest.mark.asyncio()
    async def test_stop_handles_browser_timeout(self) -> None:
        """If browser.close() hangs, stop must still finish."""
        mgr = manager_mod.PlaywrightManager()

        async def hang_forever() -> None:
            await asyncio.sleep(3600)

        br = mock.AsyncMock()
        br.close = hang_forever
        pw = mock.AsyncMock()
        mgr._browser = br
        mgr._playwright = pw
        mgr._browser_pid = None
        mgr._started = True

        await asyncio.wait_for(
            mgr.stop(),
            timeout=manager_mod._STOP_TIMEOUT_SECONDS * 2 + 10,
        )
        assert mgr._browser is None
        pw.stop.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_stop_force_kills_on_timeout(self) -> None:
        """When graceful close times out, SIGKILL the process."""
        mgr = manager_mod.PlaywrightManager()

        async def hang_forever() -> None:
            await asyncio.sleep(3600)

        br = mock.AsyncMock()
        br.close = hang_forever
        pw = mock.AsyncMock()
        mgr._browser = br
        mgr._playwright = pw
        mgr._browser_pid = 99999
        mgr._started = True

        with (
            mock.patch("os.getpgid", return_value=999),
            mock.patch("os.kill") as mock_kill,
        ):
            await asyncio.wait_for(
                mgr.stop(),
                timeout=manager_mod._STOP_TIMEOUT_SECONDS * 3 + 10,
            )
            mock_kill.assert_called_once_with(
                99999,
                signal.SIGKILL,
            )


class TestPlaywrightManagerCreateSession:
    """Validates create_session() creates isolated sessions."""

    @pytest.mark.asyncio()
    async def test_create_session_returns_bound_session(self) -> None:
        """create_session must return a session with page + listeners."""
        mgr = manager_mod.PlaywrightManager()
        br = mock.AsyncMock()
        br.is_connected = mock.Mock(return_value=True)
        ctx = mock.AsyncMock()
        page = mock.MagicMock()
        page.on = mock.Mock()
        br.new_context.return_value = ctx
        ctx.new_page.return_value = page
        mgr._browser = br
        mgr._started = True

        session = await mgr.create_session("ipad")

        assert session._context is ctx
        assert session._page is page
        page.on.assert_any_call("request", session._on_request)
        page.on.assert_any_call("response", session._on_response)

    @pytest.mark.asyncio()
    async def test_create_session_invalid_device_raises(self) -> None:
        """Unknown device types must raise ValueError."""
        mgr = manager_mod.PlaywrightManager()
        br = mock.AsyncMock()
        br.is_connected = mock.Mock(return_value=True)
        mgr._browser = br
        mgr._started = True

        with pytest.raises(ValueError, match="Unknown device type"):
            await mgr.create_session("nokia3310")  # type: ignore[arg-type]

    @pytest.mark.asyncio()
    async def test_create_session_restarts_dead_browser(self) -> None:
        """If the browser is disconnected, it should be restarted."""
        mgr = manager_mod.PlaywrightManager()
        br_dead = mock.AsyncMock()
        # is_connected() is synchronous in Playwright — use a plain Mock
        br_dead.is_connected = mock.Mock(return_value=False)
        mgr._browser = br_dead
        mgr._started = True

        # _ensure_browser calls _stop_internal + _start_browser
        # when the browser is disconnected; mock both.
        br_new = mock.AsyncMock()
        br_new.is_connected = mock.Mock(return_value=True)
        ctx = mock.AsyncMock()
        page = mock.MagicMock()
        page.on = mock.Mock()
        br_new.new_context.return_value = ctx
        ctx.new_page.return_value = page

        async def do_restart() -> None:
            mgr._browser = br_new

        with (
            mock.patch.object(
                mgr,
                "_stop_internal",
                new_callable=mock.AsyncMock,
            ) as mock_stop,
            mock.patch.object(
                mgr,
                "_start_browser",
                new_callable=mock.AsyncMock,
                side_effect=do_restart,
            ) as mock_start,
        ):
            session = await mgr.create_session("ipad")

            mock_stop.assert_awaited_once()
            mock_start.assert_awaited_once()
            assert session._context is ctx


class TestForceKillProcessGroup:
    """Validates _force_kill_browser_process kills safely."""

    def test_uses_killpg_when_different_pgid(self) -> None:
        """os.killpg is used when Chrome has its own process group."""
        mgr = manager_mod.PlaywrightManager()
        mgr._browser_pid = 42

        def fake_getpgid(pid: int) -> int:
            return 42 if pid == 42 else 1

        with (
            mock.patch("os.killpg") as mock_killpg,
            mock.patch("os.getpgid", side_effect=fake_getpgid),
            mock.patch("os.kill") as mock_kill,
        ):
            mgr._force_kill_browser_process()
            mock_killpg.assert_called_once_with(42, signal.SIGKILL)
            mock_kill.assert_not_called()

    def test_skips_killpg_when_same_pgid(self) -> None:
        """os.killpg must NOT be used when Chrome shares the server's pgid."""
        mgr = manager_mod.PlaywrightManager()
        mgr._browser_pid = 42

        with (
            mock.patch("os.killpg") as mock_killpg,
            mock.patch("os.getpgid", return_value=999),
            mock.patch("os.kill") as mock_kill,
        ):
            mgr._force_kill_browser_process()
            mock_killpg.assert_not_called()
            mock_kill.assert_called_once_with(42, signal.SIGKILL)

    def test_falls_back_to_single_kill(self) -> None:
        """If getpgid raises, falls back to os.kill."""
        mgr = manager_mod.PlaywrightManager()
        mgr._browser_pid = 42

        with (
            mock.patch("os.killpg") as mock_killpg,
            mock.patch("os.getpgid", side_effect=PermissionError),
            mock.patch("os.kill") as mock_kill,
        ):
            mgr._force_kill_browser_process()
            mock_killpg.assert_not_called()
            mock_kill.assert_called_once_with(42, signal.SIGKILL)

    def test_noop_without_pid(self) -> None:
        """No-op when no PID is available."""
        mgr = manager_mod.PlaywrightManager()
        mgr._browser_pid = None

        with (
            mock.patch("os.killpg") as mock_killpg,
            mock.patch("os.kill") as mock_kill,
        ):
            mgr._force_kill_browser_process()
            mock_killpg.assert_not_called()
            mock_kill.assert_not_called()

    def test_handles_missing_process(self) -> None:
        """Force-kill must not raise when the process is gone."""
        mgr = manager_mod.PlaywrightManager()
        mgr._browser_pid = 99999

        with (
            mock.patch("os.getpgid", side_effect=ProcessLookupError),
            mock.patch("os.kill", side_effect=ProcessLookupError),
        ):
            # Should not raise.
            mgr._force_kill_browser_process()


# ====================================================================
# BrowserSession data-capture timeout tests
# ====================================================================


class TestGetPageContentTimeout:
    """Validates that get_page_content is bounded by a timeout."""

    @pytest.mark.asyncio()
    async def test_returns_empty_on_timeout(self) -> None:
        """When page.content() hangs, return an empty string."""
        session = session_mod.BrowserSession()

        async def hang_forever() -> str:
            await asyncio.sleep(3600)
            return "<html></html>"

        page = mock.AsyncMock()
        page.content = hang_forever
        session._page = page

        result = await asyncio.wait_for(
            session.get_page_content(),
            timeout=session_mod._CAPTURE_TIMEOUT_SECONDS + 5,
        )
        assert result == ""

    @pytest.mark.asyncio()
    async def test_returns_content_on_success(self) -> None:
        """Normal page.content() returns the HTML."""
        session = session_mod.BrowserSession()
        page = mock.AsyncMock()
        page.content.return_value = "<html><body>Hello</body></html>"
        session._page = page

        result = await session.get_page_content()
        assert result == "<html><body>Hello</body></html>"

    @pytest.mark.asyncio()
    async def test_raises_without_page(self) -> None:
        """Must raise RuntimeError when no page is active."""
        session = session_mod.BrowserSession()
        with pytest.raises(RuntimeError, match="No browser session active"):
            await session.get_page_content()


class TestWaitForLoadState:
    """Validates wait_for_load_state returns bool and respects timeout."""

    @pytest.mark.asyncio()
    async def test_returns_true_on_success(self) -> None:
        """Successfully reaching a load state returns True."""
        session = session_mod.BrowserSession()
        page = mock.AsyncMock()
        session._page = page

        result = await session.wait_for_load_state("load")
        assert result is True
        page.wait_for_load_state.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_returns_false_on_timeout(self) -> None:
        """A timeout from Playwright returns False."""
        session = session_mod.BrowserSession()
        page = mock.AsyncMock()
        page.wait_for_load_state.side_effect = TimeoutError("timed out")
        session._page = page

        result = await session.wait_for_load_state("networkidle", timeout=100)
        assert result is False

    @pytest.mark.asyncio()
    async def test_raises_without_page(self) -> None:
        """Must raise RuntimeError when no page is active."""
        session = session_mod.BrowserSession()
        with pytest.raises(RuntimeError, match="No browser session active"):
            await session.wait_for_load_state()


class TestCloseTimeoutConstant:
    """Validates timeout constants are positive."""

    def test_session_close_timeout_is_positive(self) -> None:
        """Session close timeout must be positive."""
        assert session_mod._CLOSE_TIMEOUT_SECONDS > 0

    def test_manager_stop_timeout_is_positive(self) -> None:
        """Manager stop timeout must be positive."""
        assert manager_mod._STOP_TIMEOUT_SECONDS > 0

    def test_start_timeout_is_positive(self) -> None:
        """Playwright start timeout must be positive."""
        assert manager_mod._START_TIMEOUT_SECONDS > 0

    def test_health_check_timeout_is_positive(self) -> None:
        """Health-check probe timeout must be positive."""
        assert manager_mod._HEALTH_CHECK_TIMEOUT_SECONDS > 0

    def test_create_session_timeout_is_positive(self) -> None:
        """Session creation timeout must be positive."""
        assert manager_mod._CREATE_SESSION_TIMEOUT_SECONDS > 0


# ====================================================================
# Health-suspect and browser recovery tests
# ====================================================================


class TestHealthSuspect:
    """Validates mark_health_suspect and health-probe logic."""

    def test_mark_sets_flag(self) -> None:
        """mark_health_suspect must set the _health_suspect flag."""
        mgr = manager_mod.PlaywrightManager()
        assert mgr._health_suspect is False
        mgr.mark_health_suspect()
        assert mgr._health_suspect is True

    def test_mark_is_idempotent(self) -> None:
        """Calling mark_health_suspect twice is safe."""
        mgr = manager_mod.PlaywrightManager()
        mgr.mark_health_suspect()
        mgr.mark_health_suspect()
        assert mgr._health_suspect is True

    @pytest.mark.asyncio()
    async def test_healthy_browser_passes_probe(self) -> None:
        """A responsive browser passes the health probe and is kept."""
        mgr = manager_mod.PlaywrightManager()
        br = mock.AsyncMock()
        br.is_connected = mock.Mock(return_value=True)
        ctx = mock.AsyncMock()
        page = mock.MagicMock()
        page.on = mock.Mock()
        # First new_context call is the health probe (returns + close)
        # Second new_context call is the real session creation
        br.new_context.return_value = ctx
        ctx.new_page.return_value = page
        mgr._browser = br
        mgr._started = True
        mgr._health_suspect = True

        session = await mgr.create_session("ipad")

        # Health probe opens and closes a context, then the real
        # session creation opens another context + page.
        assert br.new_context.call_count >= 2
        assert session._context is ctx
        assert mgr._health_suspect is False

    @pytest.mark.asyncio()
    async def test_hung_browser_triggers_restart(self) -> None:
        """A browser that fails the health probe is restarted."""
        mgr = manager_mod.PlaywrightManager()

        # Original browser: connected but hangs on new_context
        br_old = mock.AsyncMock()
        br_old.is_connected = mock.Mock(return_value=True)

        async def hang_new_context(**kwargs: object) -> mock.AsyncMock:
            await asyncio.sleep(3600)
            return mock.AsyncMock()

        br_old.new_context = hang_new_context
        mgr._browser = br_old
        mgr._started = True
        mgr._health_suspect = True

        # Replacement browser after restart
        br_new = mock.AsyncMock()
        br_new.is_connected = mock.Mock(return_value=True)
        ctx = mock.AsyncMock()
        page = mock.MagicMock()
        page.on = mock.Mock()
        br_new.new_context.return_value = ctx
        ctx.new_page.return_value = page

        async def do_restart() -> None:
            mgr._browser = br_new

        with (
            mock.patch.object(
                mgr,
                "_stop_internal",
                new_callable=mock.AsyncMock,
            ) as mock_stop,
            mock.patch.object(
                mgr,
                "_start_browser",
                new_callable=mock.AsyncMock,
                side_effect=do_restart,
            ) as mock_start,
        ):
            session = await mgr.create_session("ipad")

            mock_stop.assert_awaited_once()
            mock_start.assert_awaited_once()
            assert session._context is ctx
            assert mgr._health_suspect is False

    @pytest.mark.asyncio()
    async def test_close_timeout_marks_manager_health_suspect(self) -> None:
        """BrowserSession.close() must flag the manager on context close timeout."""
        mgr = manager_mod.PlaywrightManager()
        session = session_mod.BrowserSession(manager=mgr)

        async def hang_forever() -> None:
            await asyncio.sleep(3600)

        ctx = mock.AsyncMock()
        ctx.close = hang_forever
        session._context = ctx

        assert mgr._health_suspect is False

        await asyncio.wait_for(
            session.close(),
            timeout=session_mod._CLOSE_TIMEOUT_SECONDS + 5,
        )

        assert session._context is None
        assert mgr._health_suspect is True

    @pytest.mark.asyncio()
    async def test_close_timeout_without_manager_is_safe(self) -> None:
        """Context close timeout without a manager reference must not raise."""
        session = session_mod.BrowserSession()  # no manager

        async def hang_forever() -> None:
            await asyncio.sleep(3600)

        ctx = mock.AsyncMock()
        ctx.close = hang_forever
        session._context = ctx

        await asyncio.wait_for(
            session.close(),
            timeout=session_mod._CLOSE_TIMEOUT_SECONDS + 5,
        )
        assert session._context is None


class TestCreateSessionTimeout:
    """Validates the outer timeout on create_session."""

    @pytest.mark.asyncio()
    async def test_timeout_marks_health_suspect(self) -> None:
        """create_session must flag health-suspect and raise on timeout."""
        mgr = manager_mod.PlaywrightManager()
        br = mock.AsyncMock()
        br.is_connected = mock.Mock(return_value=True)

        async def hang_new_context(**kwargs: object) -> mock.AsyncMock:
            await asyncio.sleep(3600)
            return mock.AsyncMock()

        br.new_context = hang_new_context
        mgr._browser = br
        mgr._started = True

        # Reduce the timeout for the test
        with mock.patch.object(
            manager_mod,
            "_CREATE_SESSION_TIMEOUT_SECONDS",
            2,
        ):
            with pytest.raises(TimeoutError):
                await mgr.create_session("ipad")

        assert mgr._health_suspect is True
