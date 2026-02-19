"""Tests for TrackingAnalysisAgent streaming inactivity timeout.

Validates that ``analyze_stream()`` raises ``TimeoutError``
when no streaming token arrives within the configured
inactivity window.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from unittest import mock

import pytest

from src.agents import base, consent_detection_agent, structured_report_agent, tracking_analysis_agent
from src.models import analysis


def _empty_summary() -> analysis.TrackingSummary:
    """Minimal TrackingSummary for testing."""
    return analysis.TrackingSummary(
        analyzed_url="https://example.com",
        total_cookies=0,
        total_scripts=0,
        total_network_requests=0,
        local_storage_items=0,
        session_storage_items=0,
        third_party_domains=[],
        domain_breakdown=[],
        local_storage=[],
        session_storage=[],
    )


class _FakeUpdate:
    """Minimal stand-in for AgentResponseUpdate."""

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeThread:
    """Minimal stand-in for a ChatThread."""

    async def serialize(self) -> str:
        return "{}"


class _FakeAgent:
    """Minimal ChatAgent stand-in with configurable stream behaviour."""

    def __init__(self, updates: list[_FakeUpdate] | None = None, hang: bool = False) -> None:
        self._updates = updates or []
        self._hang = hang

    def get_new_thread(self) -> _FakeThread:
        return _FakeThread()

    async def run_stream(self, message: object, *, thread: object) -> AsyncGenerator[_FakeUpdate]:
        """Async generator that yields updates, optionally hanging."""
        for update in self._updates:
            yield update
        if self._hang:
            # Simulate an endpoint that stops sending tokens
            await asyncio.sleep(999)


class TestStreamInactivityTimeout:
    """Tests for the streaming inactivity timeout in TrackingAnalysisAgent."""

    def _make_agent(self, timeout: float = 0.05) -> tracking_analysis_agent.TrackingAnalysisAgent:
        """Create an agent with a very short timeout for testing."""
        agent = tracking_analysis_agent.TrackingAnalysisAgent.__new__(tracking_analysis_agent.TrackingAnalysisAgent)
        agent.stream_inactivity_timeout = timeout
        agent.agent_name = "TrackingAnalysisAgent"
        return agent

    @pytest.mark.asyncio
    async def test_timeout_on_no_first_token(self) -> None:
        """TimeoutError raised when no token arrives at all."""
        agent = self._make_agent(timeout=0.05)

        fake = _FakeAgent(updates=[], hang=True)
        ctx_mgr = mock.AsyncMock()
        ctx_mgr.__aenter__ = mock.AsyncMock(return_value=fake)
        ctx_mgr.__aexit__ = mock.AsyncMock(return_value=False)

        with (
            mock.patch.object(agent, "_build_agent", return_value=ctx_mgr),
            pytest.raises(TimeoutError, match="No streaming tokens received"),
        ):
            async for _ in agent.analyze_stream(_empty_summary()):
                pass

    @pytest.mark.asyncio
    async def test_timeout_mid_stream(self) -> None:
        """TimeoutError raised when stream stalls after some tokens."""
        agent = self._make_agent(timeout=0.05)

        fake = _FakeAgent(
            updates=[_FakeUpdate("chunk1"), _FakeUpdate("chunk2")],
            hang=True,
        )
        ctx_mgr = mock.AsyncMock()
        ctx_mgr.__aenter__ = mock.AsyncMock(return_value=fake)
        ctx_mgr.__aexit__ = mock.AsyncMock(return_value=False)

        collected: list[str] = []
        with (
            mock.patch.object(agent, "_build_agent", return_value=ctx_mgr),
            pytest.raises(TimeoutError, match="Stream stalled after 2 chunks"),
        ):
            async for update in agent.analyze_stream(_empty_summary()):
                collected.append(update.text)

        # Should have received the two initial chunks before timeout
        assert collected == ["chunk1", "chunk2"]

    @pytest.mark.asyncio
    async def test_normal_stream_completes(self) -> None:
        """A well-behaved stream completes without timeout."""
        agent = self._make_agent(timeout=1.0)

        fake = _FakeAgent(
            updates=[_FakeUpdate("a"), _FakeUpdate("b"), _FakeUpdate("c")],
            hang=False,
        )
        ctx_mgr = mock.AsyncMock()
        ctx_mgr.__aenter__ = mock.AsyncMock(return_value=fake)
        ctx_mgr.__aexit__ = mock.AsyncMock(return_value=False)

        collected: list[str] = []
        with mock.patch.object(agent, "_build_agent", return_value=ctx_mgr):
            async for update in agent.analyze_stream(_empty_summary()):
                collected.append(update.text)

        assert collected == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_timeout_message_includes_duration(self) -> None:
        """Error message includes the configured timeout value."""
        agent = self._make_agent(timeout=0.05)

        fake = _FakeAgent(updates=[], hang=True)
        ctx_mgr = mock.AsyncMock()
        ctx_mgr.__aenter__ = mock.AsyncMock(return_value=fake)
        ctx_mgr.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch.object(agent, "_build_agent", return_value=ctx_mgr), pytest.raises(TimeoutError, match=r"0\.05s"):
            async for _ in agent.analyze_stream(_empty_summary()):
                pass


class TestDefaultTimeoutValues:
    """Verify default timeout settings are at the expected values."""

    def test_base_agent_default_timeout(self) -> None:
        assert base.BaseAgent.call_timeout == 30

    def test_consent_detection_timeout(self) -> None:
        assert consent_detection_agent.ConsentDetectionAgent.call_timeout == 30

    def test_structured_report_timeout(self) -> None:
        assert structured_report_agent.StructuredReportAgent.call_timeout == 60

    def test_streaming_inactivity_timeout(self) -> None:
        assert tracking_analysis_agent.TrackingAnalysisAgent.stream_inactivity_timeout == 60
