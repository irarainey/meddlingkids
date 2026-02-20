"""Tests for src.agents.base — BaseAgent helpers."""

from __future__ import annotations

import json
from unittest import mock

import agent_framework
import pydantic

from src.agents.base import BaseAgent


# ── Helper model ──────────────────────────────────────────────


class _SampleModel(pydantic.BaseModel):
    """Tiny model for testing _parse_response."""

    name: str
    count: int


class TestPrepareStrictSchema:
    """Validates that _prepare_strict_schema patches schemas for Azure strict mode."""

    def test_adds_additional_properties(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        }
        result = BaseAgent._prepare_strict_schema(schema)
        assert result["additionalProperties"] is False
        assert result["required"] == ["name"]

    def test_nested_objects(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "child": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "integer"},
                    },
                },
            },
        }
        result = BaseAgent._prepare_strict_schema(schema)
        child = result["properties"]["child"]
        assert child["additionalProperties"] is False
        assert child["required"] == ["value"]

    def test_array_items(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                        },
                    },
                },
            },
        }
        result = BaseAgent._prepare_strict_schema(schema)
        item_schema = result["properties"]["items"]["items"]
        assert item_schema["additionalProperties"] is False

    def test_defs_patched(self) -> None:
        schema = {
            "type": "object",
            "properties": {},
            "$defs": {
                "Nested": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                    },
                },
            },
        }
        result = BaseAgent._prepare_strict_schema(schema)
        assert result["$defs"]["Nested"]["additionalProperties"] is False

    def test_does_not_mutate_input(self) -> None:
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        BaseAgent._prepare_strict_schema(schema)
        assert "additionalProperties" not in schema

    def test_anyof_variants_patched(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "field": {
                    "anyOf": [
                        {"type": "object", "properties": {"v": {"type": "string"}}},
                        {"type": "string"},
                    ],
                },
            },
        }
        result = BaseAgent._prepare_strict_schema(schema)
        variant = result["properties"]["field"]["anyOf"][0]
        assert variant["additionalProperties"] is False


class TestParseResponse:
    """Validates _parse_response directly parses response.text."""

    def _agent(self) -> BaseAgent:
        agent = BaseAgent.__new__(BaseAgent)
        agent.agent_name = "TestAgent"
        return agent

    def _response(self, text: str) -> agent_framework.AgentResponse:
        return agent_framework.AgentResponse(
            messages=[
                agent_framework.Message(role="assistant", text=text),
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


class TestFallbackClient:
    """Validates deployment fallback behaviour."""

    def test_no_fallback_without_override(self) -> None:
        """Agent without a deployment override has no fallback."""
        agent = BaseAgent()
        assert agent.has_fallback is False
        assert agent.activate_fallback() is False

    def test_has_fallback_with_override(self) -> None:
        """Agent initialised with a deployment override prepares a fallback."""
        agent = BaseAgent()
        primary = mock.MagicMock()
        fallback = mock.MagicMock()
        agent._chat_client = primary
        agent._fallback_client = fallback
        assert agent.has_fallback is True

    def test_activate_fallback_switches_client(self) -> None:
        """activate_fallback replaces the primary with the fallback."""
        agent = BaseAgent()
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
        agent = BaseAgent()
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
        agent = BaseAgent()
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
        assert mock_get.call_count == 2
        # First call with override, second without.
        mock_get.assert_any_call(
            agent_name="ScriptAnalysisAgent",
            deployment_override="codex-mini",
        )
        mock_get.assert_any_call(
            agent_name="ScriptAnalysisAgent",
        )

    def test_initialise_no_fallback_without_override(
        self,
    ) -> None:
        """initialise() skips fallback when no override exists."""
        agent = BaseAgent()
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
