"""Tests for src.agents.base — BaseAgent helpers."""

from __future__ import annotations

import json
from unittest import mock

import agent_framework
import pydantic

from src.agents import base

# ── Helper model ──────────────────────────────────────────────


class _SampleModel(pydantic.BaseModel):
    """Tiny model for testing _parse_response."""

    name: str
    count: int


class TestParseResponse:
    """Validates _parse_response uses response.value then falls back to text."""

    def _agent(self) -> base.BaseAgent:
        agent = base.BaseAgent.__new__(base.BaseAgent)
        agent.agent_name = "TestAgent"
        return agent

    def _response(self, text: str) -> agent_framework.AgentResponse:
        return agent_framework.AgentResponse(
            messages=[
                agent_framework.Message(role="assistant", contents=[text]),
            ],
        )

    def test_parses_valid_json(self) -> None:
        """Valid JSON in response.text is parsed into the model."""
        agent = self._agent()
        resp = self._response(json.dumps({"name": "foo", "count": 42}))
        result = agent._parse_response(resp, _SampleModel)
        assert result is not None
        assert result.name == "foo"
        assert result.count == 42

    def test_uses_response_value_when_available(self) -> None:
        """When response.value returns a matching model, use it directly."""
        agent = self._agent()
        expected = _SampleModel(name="bar", count=7)
        resp = self._response(json.dumps({"name": "bar", "count": 7}))
        resp._value = expected  # type: ignore[assignment]
        resp._value_parsed = True
        result = agent._parse_response(resp, _SampleModel)
        assert result is expected

    def test_falls_back_to_text_when_value_wrong_type(self) -> None:
        """When response.value returns wrong type, fall back to text parsing."""
        agent = self._agent()
        resp = self._response(json.dumps({"name": "baz", "count": 99}))
        resp._value = "not a model"  # type: ignore[assignment]
        resp._value_parsed = True
        result = agent._parse_response(resp, _SampleModel)
        assert result is not None
        assert result.name == "baz"

    def test_returns_none_for_invalid_json(self) -> None:
        """Non-JSON text returns None (no crash)."""
        agent = self._agent()
        resp = self._response("not json at all")
        result = agent._parse_response(resp, _SampleModel)
        assert result is None

    def test_returns_none_for_empty_text(self) -> None:
        """Empty response text returns None."""
        agent = self._agent()
        resp = self._response("")
        result = agent._parse_response(resp, _SampleModel)
        assert result is None

    def test_returns_none_for_schema_mismatch(self) -> None:
        """JSON that doesn't match the model returns None."""
        agent = self._agent()
        resp = self._response(json.dumps({"wrong": "fields"}))
        result = agent._parse_response(resp, _SampleModel)
        assert result is None


class TestBuildOptions:
    """Validates _build_options passes Pydantic models directly to response_format."""

    def test_response_format_is_pydantic_class(self) -> None:
        """response_format should be the model class, not a dict schema."""
        agent = base.BaseAgent.__new__(base.BaseAgent)
        agent.agent_name = "TestAgent"
        agent.max_tokens = 1024
        agent.response_model = _SampleModel
        agent.temperature = None
        agent.seed = None
        opts = agent._build_options()
        assert opts["response_format"] is _SampleModel

    def test_no_response_format_without_model(self) -> None:
        """response_format is absent when no model is set."""
        agent = base.BaseAgent.__new__(base.BaseAgent)
        agent.agent_name = "TestAgent"
        agent.max_tokens = 1024
        agent.response_model = None
        agent.temperature = None
        agent.seed = None
        opts = agent._build_options()
        assert "response_format" not in opts


class TestFallbackClient:
    """Validates deployment fallback behaviour."""

    def test_no_fallback_without_override(self) -> None:
        """Agent without a deployment override has no fallback."""
        agent = base.BaseAgent()
        assert agent.has_fallback is False
        assert agent.activate_fallback() is False

    def test_has_fallback_with_override(self) -> None:
        """Agent initialised with a deployment override prepares a fallback."""
        agent = base.BaseAgent()
        primary = mock.MagicMock()
        fallback = mock.MagicMock()
        agent._chat_client = primary
        agent._fallback_client = fallback
        assert agent.has_fallback is True

    def test_activate_fallback_switches_client(self) -> None:
        """activate_fallback replaces the primary with the fallback."""
        agent = base.BaseAgent()
        primary = mock.MagicMock()
        fallback = mock.MagicMock()
        agent._chat_client = primary
        agent._fallback_client = fallback

        result = agent.activate_fallback()

        assert result is True
        assert agent._chat_client is fallback
        assert agent._fallback_client is None
        assert agent._using_fallback is True

    def test_activate_fallback_only_once(self) -> None:
        """Fallback can only be activated once."""
        agent = base.BaseAgent()
        agent._chat_client = mock.MagicMock()
        agent._fallback_client = mock.MagicMock()

        assert agent.activate_fallback() is True
        assert agent.has_fallback is False
        assert agent.activate_fallback() is False

    def test_initialise_creates_fallback_with_override(
        self,
    ) -> None:
        """initialise() creates a fallback when a deployment
        override is configured."""
        agent = base.BaseAgent()
        agent.agent_name = "ScriptAnalysisAgent"

        primary = mock.MagicMock()
        fallback = mock.MagicMock()

        with (
            mock.patch(
                "src.agents.config.get_agent_deployment",
                return_value="codex-mini",
            ),
            mock.patch(
                "src.agents.llm_client.get_chat_client",
                side_effect=[primary, fallback],
            ) as mock_get,
        ):
            result = agent.initialise()

        assert result is True
        assert agent._chat_client is primary
        assert agent._fallback_client is fallback
        assert agent._deployment == "codex-mini"
        assert mock_get.call_count == 2
        # First call with override, second without.
        mock_get.assert_any_call(
            agent_name="ScriptAnalysisAgent",
            deployment_override="codex-mini",
            use_responses_api=False,
        )
        mock_get.assert_any_call(
            agent_name="ScriptAnalysisAgent",
        )

    def test_initialise_no_fallback_without_override(
        self,
    ) -> None:
        """initialise() skips fallback when no override exists."""
        agent = base.BaseAgent()
        agent.agent_name = "TrackingAnalysisAgent"

        client = mock.MagicMock()
        with (
            mock.patch(
                "src.agents.config.get_agent_deployment",
                return_value=None,
            ),
            mock.patch(
                "src.agents.llm_client.get_chat_client",
                return_value=client,
            ) as mock_get,
        ):
            result = agent.initialise()

        assert result is True
        assert agent._chat_client is client
        assert agent._fallback_client is None
        mock_get.assert_called_once()
