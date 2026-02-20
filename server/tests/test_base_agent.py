"""Tests for src.agents.base — BaseAgent._prepare_strict_schema."""

from __future__ import annotations

from unittest import mock

from src.agents.base import BaseAgent


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
