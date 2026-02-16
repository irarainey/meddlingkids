"""Tests for BrowserSession cleanup and resource disposal.

Validates that close() handles graceful shutdown, timeouts on
hung processes, and OS-level force-kill as a last resort.
Also tests browser_phases.launch_browser retry logic.
"""

from __future__ import annotations

import asyncio
import signal
from unittest import mock

import pytest

from src.browser import session as session_mod
from src.pipeline import browser_phases


class TestBrowserSessionClose:
    """Validates BrowserSession.close() cleanup behaviour."""

    @pytest.mark.asyncio()
    async def test_close_on_fresh_session_is_noop(self) -> None:
        """Closing a never-launched session must not raise."""
        session = session_mod.BrowserSession()
        await session.close()
        assert session._playwright is None
        assert session._browser is None
        assert session._context is None
        assert session._page is None

    @pytest.mark.asyncio()
    async def test_close_removes_event_listeners(self) -> None:
        """Page event listeners must be removed before closing."""
        session = session_mod.BrowserSession()
        page = mock.AsyncMock()
        session._page = page

        await session.close()

        page.remove_listener.assert_any_call(
            "request", session._on_request,
        )
        page.remove_listener.assert_any_call(
            "response", session._on_response,
        )
        assert session._page is None

    @pytest.mark.asyncio()
    async def test_close_calls_each_layer(self) -> None:
        """Close must shut down context, browser, and playwright."""
        session = session_mod.BrowserSession()
        ctx = mock.AsyncMock()
        br = mock.AsyncMock()
        pw = mock.AsyncMock()

        session._context = ctx
        session._browser = br
        session._playwright = pw

        await session.close()

        ctx.close.assert_awaited_once()
        br.close.assert_awaited_once()
        pw.stop.assert_awaited_once()
        assert session._context is None
        assert session._browser is None
        assert session._playwright is None

    @pytest.mark.asyncio()
    async def test_close_handles_context_timeout(self) -> None:
        """If context.close() hangs, close must not block forever."""
        session = session_mod.BrowserSession()

        async def hang_forever() -> None:
            await asyncio.sleep(3600)

        ctx = mock.AsyncMock()
        ctx.close = hang_forever
        br = mock.AsyncMock()
        pw = mock.AsyncMock()
        session._context = ctx
        session._browser = br
        session._playwright = pw
        session._browser_pid = None

        # close() should complete within a reasonable time
        # (not hang for the full 3600s).
        await asyncio.wait_for(
            session.close(),
            timeout=session_mod._CLOSE_TIMEOUT_SECONDS + 5,
        )
        assert session._context is None
        br.close.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_close_handles_browser_timeout(self) -> None:
        """If browser.close() hangs, close must still finish."""
        session = session_mod.BrowserSession()

        async def hang_forever() -> None:
            await asyncio.sleep(3600)

        br = mock.AsyncMock()
        br.close = hang_forever
        pw = mock.AsyncMock()
        session._browser = br
        session._playwright = pw
        session._browser_pid = None

        await asyncio.wait_for(
            session.close(),
            timeout=session_mod._CLOSE_TIMEOUT_SECONDS * 2 + 5,
        )
        assert session._browser is None
        pw.stop.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_close_force_kills_on_timeout(self) -> None:
        """When graceful close times out, SIGKILL the process."""
        session = session_mod.BrowserSession()

        async def hang_forever() -> None:
            await asyncio.sleep(3600)

        br = mock.AsyncMock()
        br.close = hang_forever
        pw = mock.AsyncMock()
        session._browser = br
        session._playwright = pw
        session._browser_pid = 99999

        with mock.patch("os.kill") as mock_kill:
            await asyncio.wait_for(
                session.close(),
                timeout=session_mod._CLOSE_TIMEOUT_SECONDS * 3 + 10,
            )
            mock_kill.assert_called_once_with(
                99999, signal.SIGKILL,
            )

    @pytest.mark.asyncio()
    async def test_force_kill_handles_missing_process(
        self,
    ) -> None:
        """Force-kill must not raise when the process is gone."""
        session = session_mod.BrowserSession()
        session._browser_pid = 99999

        with mock.patch(
            "os.kill",
            side_effect=ProcessLookupError,
        ):
            # Should not raise.
            session._force_kill_browser_process()

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
        session._browser_pid = 12345

        await session.close()

        assert len(session._tracked_cookies) == 0
        assert len(session._tracked_scripts) == 0
        assert len(session._tracked_network_requests) == 0
        assert len(session._seen_script_urls) == 0
        assert session._browser_pid is None

    @pytest.mark.asyncio()
    async def test_close_continues_after_context_error(
        self,
    ) -> None:
        """An exception in context.close() must not stop cleanup."""
        session = session_mod.BrowserSession()
        ctx = mock.AsyncMock()
        ctx.close.side_effect = RuntimeError("oops")
        br = mock.AsyncMock()
        pw = mock.AsyncMock()
        session._context = ctx
        session._browser = br
        session._playwright = pw

        await session.close()

        # Browser and playwright must still be closed.
        br.close.assert_awaited_once()
        pw.stop.assert_awaited_once()


class TestBrowserSessionContextManager:
    """Validates async context manager protocol."""

    @pytest.mark.asyncio()
    async def test_aexit_calls_close(self) -> None:
        """Exiting the context manager must call close()."""
        session = session_mod.BrowserSession()
        with mock.patch.object(
            session, "close", new_callable=mock.AsyncMock,
        ) as mock_close:
            async with session:
                pass
            mock_close.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_aexit_calls_close_on_exception(self) -> None:
        """close() must be called even when the body raises."""
        session = session_mod.BrowserSession()
        with mock.patch.object(
            session, "close", new_callable=mock.AsyncMock,
        ) as mock_close:
            with pytest.raises(ValueError, match="boom"):
                async with session:
                    raise ValueError("boom")
            mock_close.assert_awaited_once()


class TestPlaywrightStartTimeout:
    """Validates that Playwright startup is time-bounded."""

    def test_timeout_constant_is_positive(self) -> None:
        """Sanity-check: the timeout must be a positive value."""
        assert session_mod._PLAYWRIGHT_START_TIMEOUT_SECONDS > 0

    def test_close_timeout_constant_is_positive(self) -> None:
        """Sanity-check: close timeout must be positive."""
        assert session_mod._CLOSE_TIMEOUT_SECONDS > 0


class TestBrowserLaunchRetry:
    """Validates browser_phases.launch_browser retry logic."""

    @pytest.mark.asyncio()
    async def test_succeeds_on_first_attempt(self) -> None:
        """No retry needed when launch succeeds immediately."""
        session = mock.AsyncMock(spec=session_mod.BrowserSession)
        session.launch_browser = mock.AsyncMock()

        await browser_phases.launch_browser(session, "ipad")

        session.launch_browser.assert_awaited_once_with("ipad")
        session.close.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_retries_after_first_failure(self) -> None:
        """A transient failure triggers cleanup and retry."""
        session = mock.AsyncMock(spec=session_mod.BrowserSession)
        session.launch_browser = mock.AsyncMock(
            side_effect=[RuntimeError("crash"), None],
        )

        # Patch the delay so the test doesn't wait.
        with mock.patch.object(
            browser_phases, "_RETRY_DELAY_SECONDS", 0,
        ):
            await browser_phases.launch_browser(
                session, "ipad",
            )

        assert session.launch_browser.await_count == 2
        # Cleanup must be called between attempts.
        session.close.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_raises_after_all_attempts_fail(self) -> None:
        """When all attempts fail, the last error propagates."""
        session = mock.AsyncMock(spec=session_mod.BrowserSession)
        session.launch_browser = mock.AsyncMock(
            side_effect=RuntimeError("display dead"),
        )

        with mock.patch.object(
            browser_phases, "_RETRY_DELAY_SECONDS", 0,
        ):
            with pytest.raises(
                RuntimeError, match="display dead",
            ):
                await browser_phases.launch_browser(
                    session, "ipad",
                )

        assert (
            session.launch_browser.await_count
            == browser_phases._MAX_LAUNCH_ATTEMPTS
        )

    @pytest.mark.asyncio()
    async def test_cleanup_failure_between_retries_is_non_fatal(
        self,
    ) -> None:
        """If cleanup between retries fails, retry still proceeds."""
        session = mock.AsyncMock(spec=session_mod.BrowserSession)
        session.launch_browser = mock.AsyncMock(
            side_effect=[RuntimeError("crash"), None],
        )
        session.close = mock.AsyncMock(
            side_effect=RuntimeError("cleanup boom"),
        )

        with mock.patch.object(
            browser_phases, "_RETRY_DELAY_SECONDS", 0,
        ):
            await browser_phases.launch_browser(
                session, "ipad",
            )

        # Second attempt must succeed despite cleanup failure.
        assert session.launch_browser.await_count == 2
