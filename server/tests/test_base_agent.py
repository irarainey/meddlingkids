"""Tests for src.agents.base — BaseAgent._prepare_strict_schema."""

from __future__ import annotations

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
