"""Tests for src.utils.json_parsing — LLM response JSON parsing."""

from __future__ import annotations

from src.utils.json_parsing import load_json_from_text


class TestLoadJsonFromText:
    """Tests for load_json_from_text()."""

    def test_plain_json(self) -> None:
        result = load_json_from_text('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_markdown_fences(self) -> None:
        text = '```json\n{"key": "value"}\n```'
        result = load_json_from_text(text)
        assert result == {"key": "value"}

    def test_json_with_language_fence(self) -> None:
        text = '```javascript\n{"key": "value"}\n```'
        result = load_json_from_text(text)
        assert result == {"key": "value"}

    def test_json_array(self) -> None:
        result = load_json_from_text("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_json_array_with_fences(self) -> None:
        text = "```json\n[1, 2, 3]\n```"
        result = load_json_from_text(text)
        assert result == [1, 2, 3]

    def test_invalid_json_returns_none(self) -> None:
        assert load_json_from_text("not json at all") is None

    def test_none_input_returns_none(self) -> None:
        assert load_json_from_text(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert load_json_from_text("") is None

    def test_whitespace_around_json(self) -> None:
        result = load_json_from_text('  {"key": 42}  ')
        assert result == {"key": 42}

    def test_nested_json(self) -> None:
        text = '{"outer": {"inner": [1, 2]}}'
        result = load_json_from_text(text)
        assert result == {"outer": {"inner": [1, 2]}}

    def test_fences_without_language_tag(self) -> None:
        text = '```\n{"key": "value"}\n```'
        result = load_json_from_text(text)
        assert result == {"key": "value"}

    def test_boolean_and_null(self) -> None:
        result = load_json_from_text('{"a": true, "b": false, "c": null}')
        assert result == {"a": True, "b": False, "c": None}
