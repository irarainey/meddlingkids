"""Tests for src.agents.script_analysis_agent.

Covers the ``_is_model_error`` and ``_is_codex_deployment``
helpers and the ``ScriptAnalysisAgent.analyze_one`` behaviour
for both chat-completion and legacy-completion (Codex) paths.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from src.agents import script_analysis_agent


# ── _is_codex_deployment ─────────────────────────────────────


class TestIsCodexDeployment:
    """Validates Codex model detection."""

    def test_codex_mini(self) -> None:
        assert script_analysis_agent._is_codex_deployment("gpt-5.1-codex-mini") is True

    def test_codex_uppercase(self) -> None:
        assert script_analysis_agent._is_codex_deployment("GPT-5.1-CODEX-MINI") is True

    def test_codex_embedded(self) -> None:
        assert script_analysis_agent._is_codex_deployment("my-codex-deployment") is True

    def test_chat_model(self) -> None:
        assert script_analysis_agent._is_codex_deployment("gpt-5.2-chat") is False

    def test_none(self) -> None:
        assert script_analysis_agent._is_codex_deployment(None) is False

    def test_empty(self) -> None:
        assert script_analysis_agent._is_codex_deployment("") is False


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
        resp.text = json.dumps({"description": "Ad script"})
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
        fallback_resp.text = json.dumps(
            {"description": "Tracking pixel"},
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


# ── Codex completion path ────────────────────────────────────


class TestCodexCompletionPath:
    """Validates the Codex (legacy Completions API) path."""

    @pytest.fixture
    def codex_agent(self) -> script_analysis_agent.ScriptAnalysisAgent:
        """Create an agent configured for a Codex deployment."""
        a = script_analysis_agent.ScriptAnalysisAgent()
        a._deployment = "gpt-5.1-codex-mini"
        a._using_fallback = False

        # Mock the chat client with an underlying SDK client
        sdk_client = mock.AsyncMock()
        chat_client = mock.MagicMock()
        chat_client.client = sdk_client
        a._chat_client = chat_client
        a._fallback_client = mock.MagicMock()
        return a

    def test_uses_codex_property(
        self,
        codex_agent: script_analysis_agent.ScriptAnalysisAgent,
    ) -> None:
        """_uses_codex returns True for codex deployments."""
        assert codex_agent._uses_codex is True

    def test_uses_codex_after_fallback(
        self,
        codex_agent: script_analysis_agent.ScriptAnalysisAgent,
    ) -> None:
        """_uses_codex returns False once fallback is active."""
        codex_agent._using_fallback = True
        assert codex_agent._uses_codex is False

    def test_uses_codex_chat_model(self) -> None:
        """_uses_codex returns False for chat models."""
        a = script_analysis_agent.ScriptAnalysisAgent()
        a._deployment = "gpt-5.2-chat"
        a._using_fallback = False
        assert a._uses_codex is False

    @pytest.mark.asyncio
    async def test_codex_success(
        self,
        codex_agent: script_analysis_agent.ScriptAnalysisAgent,
    ) -> None:
        """Codex path returns description from JSON response."""
        completion = mock.MagicMock()
        choice = mock.MagicMock()
        choice.text = '{"description": "Google Analytics tracking"}'
        completion.choices = [choice]

        sdk_client = codex_agent._chat_client.client
        sdk_client.completions.create = mock.AsyncMock(
            return_value=completion,
        )

        result = await codex_agent.analyze_one(
            "https://example.com/ga.js",
            "function ga(){}",
        )
        assert result == "Google Analytics tracking"
        sdk_client.completions.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_codex_plain_text_fallback(
        self,
        codex_agent: script_analysis_agent.ScriptAnalysisAgent,
    ) -> None:
        """Codex path accepts plain text when JSON is absent."""
        completion = mock.MagicMock()
        choice = mock.MagicMock()
        choice.text = "Facebook Pixel tracking script"
        completion.choices = [choice]

        sdk_client = codex_agent._chat_client.client
        sdk_client.completions.create = mock.AsyncMock(
            return_value=completion,
        )

        result = await codex_agent.analyze_one(
            "https://example.com/fbevents.js",
        )
        assert result == "Facebook Pixel tracking script"

    @pytest.mark.asyncio
    async def test_codex_empty_response(
        self,
        codex_agent: script_analysis_agent.ScriptAnalysisAgent,
    ) -> None:
        """Codex path returns None for empty responses."""
        completion = mock.MagicMock()
        choice = mock.MagicMock()
        choice.text = ""
        completion.choices = [choice]

        sdk_client = codex_agent._chat_client.client
        sdk_client.completions.create = mock.AsyncMock(
            return_value=completion,
        )

        result = await codex_agent.analyze_one(
            "https://example.com/empty.js",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_codex_error_triggers_fallback(
        self,
        codex_agent: script_analysis_agent.ScriptAnalysisAgent,
    ) -> None:
        """Codex model error triggers fallback to chat model."""
        sdk_client = codex_agent._chat_client.client
        sdk_client.completions.create = mock.AsyncMock(
            side_effect=Exception("OperationNotSupported"),
        )

        fallback_resp = mock.MagicMock()
        fallback_resp.text = json.dumps({"description": "Ad script"})

        with mock.patch.object(
            codex_agent,
            "_complete",
            return_value=fallback_resp,
        ):
            result = await codex_agent.analyze_one(
                "https://example.com/ads.js",
            )

        assert result == "Ad script"
        assert codex_agent._using_fallback is True

    @pytest.mark.asyncio
    async def test_codex_ensure_client_fallback(self) -> None:
        """Uses _ensure_client when client attribute is None."""
        a = script_analysis_agent.ScriptAnalysisAgent()
        a._deployment = "gpt-5.1-codex-mini"
        a._using_fallback = False
        a._fallback_client = mock.MagicMock()

        sdk_client = mock.AsyncMock()
        completion = mock.MagicMock()
        choice = mock.MagicMock()
        choice.text = '{"description": "Widget script"}'
        completion.choices = [choice]
        sdk_client.completions.create = mock.AsyncMock(
            return_value=completion,
        )

        chat_client = mock.MagicMock()
        chat_client.client = None
        chat_client._ensure_client = mock.AsyncMock(
            return_value=sdk_client,
        )
        a._chat_client = chat_client

        result = await a.analyze_one("https://cdn.example.com/widget.js")
        assert result == "Widget script"