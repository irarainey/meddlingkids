"""Tests for src.agents.script_analysis_agent.

Covers the ``_is_model_error`` helper and the
``ScriptAnalysisAgent.analyze_one`` fallback behaviour.
"""

from __future__ import annotations

from unittest import mock

import pytest

from src.agents import script_analysis_agent

# ── _is_model_error ──────────────────────────────────────────


class TestIsModelError:
    """Validates detection of permanent model errors."""

    def test_operation_not_supported(self) -> None:
        err = Exception(
            "Error code: 400 - {'error': {'code':"
            " 'OperationNotSupported', 'message':"
            " 'The chatCompletion operation does not"
            " work with the specified model'}}"
        )
        assert script_analysis_agent._is_model_error(err) is True

    def test_does_not_work_with_model(self) -> None:
        err = Exception("does not work with the specified model, gpt-5.1-codex-mini")
        assert script_analysis_agent._is_model_error(err) is True

    def test_rate_limit_is_not_model_error(self) -> None:
        err = Exception("429 rate limit exceeded")
        assert script_analysis_agent._is_model_error(err) is False

    def test_timeout_is_not_model_error(self) -> None:
        err = TimeoutError("LLM call timed out")
        assert script_analysis_agent._is_model_error(err) is False

    def test_generic_error_is_not_model_error(self) -> None:
        err = Exception("something went wrong")
        assert script_analysis_agent._is_model_error(err) is False

    def test_empty_message(self) -> None:
        err = Exception("")
        assert script_analysis_agent._is_model_error(err) is False


# ── ScriptAnalysisAgent.analyze_one ──────────────────────────


class TestAnalyzeOneFallback:
    """Validates the fallback flow when the override model fails."""

    @pytest.fixture
    def agent(self) -> script_analysis_agent.ScriptAnalysisAgent:
        """Create an agent with mocked clients."""
        a = script_analysis_agent.ScriptAnalysisAgent()
        a._chat_client = mock.MagicMock()
        a._fallback_client = mock.MagicMock()
        a._using_fallback = False
        return a

    @pytest.mark.asyncio
    async def test_success_without_fallback(
        self,
        agent: script_analysis_agent.ScriptAnalysisAgent,
    ) -> None:
        """Normal path: override model succeeds."""
        resp = mock.MagicMock()
        resp.value = mock.MagicMock(description="Ad script")
        with mock.patch.object(
            agent,
            "_complete",
            return_value=resp,
        ):
            result = await agent.analyze_one(
                "https://example.com/ads.js",
            )
        assert result == "Ad script"
        # Fallback was not activated.
        assert agent._using_fallback is False

    @pytest.mark.asyncio
    async def test_fallback_on_model_error(
        self,
        agent: script_analysis_agent.ScriptAnalysisAgent,
    ) -> None:
        """Override model fails → fallback is activated and
        the retry succeeds."""
        model_err = Exception("OperationNotSupported: chatCompletion does not work with the specified model")
        fallback_resp = mock.MagicMock()
        fallback_resp.value = mock.MagicMock(
            description="Tracking pixel",
        )

        call_count = 0

        async def side_effect(*_a, **_kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise model_err
            return fallback_resp

        with mock.patch.object(
            agent,
            "_complete",
            side_effect=side_effect,
        ):
            result = await agent.analyze_one(
                "https://example.com/pixel.js",
            )

        assert result == "Tracking pixel"
        assert agent._using_fallback is True

    @pytest.mark.asyncio
    async def test_no_fallback_on_retryable_error(
        self,
        agent: script_analysis_agent.ScriptAnalysisAgent,
    ) -> None:
        """Rate-limit errors do not trigger fallback."""
        err = Exception("429 rate limit exceeded")
        with mock.patch.object(
            agent,
            "_complete",
            side_effect=err,
        ):
            result = await agent.analyze_one(
                "https://example.com/script.js",
            )
        assert result is None
        # Fallback was NOT activated for a retryable error.
        assert agent._using_fallback is False

    @pytest.mark.asyncio
    async def test_no_double_fallback(
        self,
        agent: script_analysis_agent.ScriptAnalysisAgent,
    ) -> None:
        """Once already on the fallback, model errors return
        None instead of looping."""
        agent._using_fallback = True
        agent._fallback_client = None
        err = Exception("OperationNotSupported")
        with mock.patch.object(
            agent,
            "_complete",
            side_effect=err,
        ):
            result = await agent.analyze_one(
                "https://example.com/script.js",
            )
        assert result is None
