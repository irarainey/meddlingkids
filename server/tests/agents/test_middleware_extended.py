"""Extended tests for agent middleware — timing, response description, and helpers."""

from __future__ import annotations

from unittest import mock

import pytest

from src.agents.middleware import (
    EmptyResponseError,
    OutputTruncatedError,
    TimingChatMiddleware,
    _describe_response,
    _estimate_message_chars,
    _is_retryable,
)


class TestEstimateMessageChars:
    """Tests for _estimate_message_chars()."""

    def test_empty_list(self) -> None:
        assert _estimate_message_chars([]) == 0

    def test_messages_with_text(self) -> None:
        msg1 = mock.MagicMock()
        msg1.text = "Hello, world!"
        msg2 = mock.MagicMock()
        msg2.text = "How are you?"
        assert _estimate_message_chars([msg1, msg2]) == 25

    def test_messages_without_text(self) -> None:
        msg = mock.MagicMock(spec=[])
        assert _estimate_message_chars([msg]) == 0

    def test_message_with_none_text(self) -> None:
        msg = mock.MagicMock()
        msg.text = None
        assert _estimate_message_chars([msg]) == 0


class TestDescribeResponse:
    """Tests for _describe_response()."""

    def test_none_result(self) -> None:
        assert _describe_response(None) == "(no metadata)"

    def test_with_finish_reason(self) -> None:
        result = mock.MagicMock(spec=["finish_reason"])
        result.finish_reason = "stop"
        desc = _describe_response(result)
        assert "finish_reason=stop" in desc

    def test_with_model_id(self) -> None:
        result = mock.MagicMock(spec=["model_id"])
        result.model_id = "gpt-4o"
        desc = _describe_response(result)
        assert "model=gpt-4o" in desc

    def test_with_usage_details(self) -> None:
        result = mock.MagicMock(spec=["usage_details"])
        result.usage_details = {"input_token_count": 100, "output_token_count": 50}
        desc = _describe_response(result)
        assert "input_tokens=100" in desc
        assert "output_tokens=50" in desc

    def test_with_additional_properties(self) -> None:
        result = mock.MagicMock(spec=["additional_properties"])
        result.additional_properties = {"key": "value"}
        desc = _describe_response(result)
        assert "extra=" in desc

    def test_with_all_fields(self) -> None:
        result = mock.MagicMock()
        result.finish_reason = "stop"
        result.model_id = "gpt-4o"
        result.usage_details = {"input_token_count": 1000, "output_token_count": 500}
        result.additional_properties = None
        desc = _describe_response(result)
        assert "finish_reason=stop" in desc
        assert "model=gpt-4o" in desc


class TestOutputTruncatedError:
    """Tests for OutputTruncatedError."""

    def test_is_subclass_of_empty_response(self) -> None:
        assert issubclass(OutputTruncatedError, EmptyResponseError)

    def test_not_retryable(self) -> None:
        assert not _is_retryable(OutputTruncatedError("truncated"))

    def test_message(self) -> None:
        err = OutputTruncatedError("Agent X output exceeded max_tokens")
        assert "max_tokens" in str(err)


class TestTimingChatMiddleware:
    """Tests for TimingChatMiddleware initialization."""

    def test_default_agent_name(self) -> None:
        mw = TimingChatMiddleware()
        assert mw.agent_name == "Unknown"

    def test_custom_agent_name(self) -> None:
        mw = TimingChatMiddleware("MyAgent")
        assert mw.agent_name == "MyAgent"

    @pytest.mark.asyncio
    async def test_process_records_timing(self) -> None:
        mw = TimingChatMiddleware("TestAgent")

        async def call_next() -> None:
            pass

        context = mock.MagicMock()
        context.messages = []
        context.result = None
        context.metadata = {}

        await mw.process(context, call_next)
        assert "timing" in context.metadata
        assert context.metadata["timing"]["agent_name"] == "TestAgent"
        assert "duration_seconds" in context.metadata["timing"]

    @pytest.mark.asyncio
    async def test_records_usage_without_details(self) -> None:
        mw = TimingChatMiddleware("TestAgent")

        async def call_next() -> None:
            pass

        result = mock.MagicMock(spec=[])  # No usage_details
        context = mock.MagicMock()
        context.messages = []
        context.result = result
        context.metadata = {}

        await mw.process(context, call_next)

    @pytest.mark.asyncio
    async def test_records_usage_with_details(self) -> None:
        mw = TimingChatMiddleware("TestAgent")

        async def call_next() -> None:
            pass

        result = mock.MagicMock()
        result.usage_details = {
            "input_token_count": 100,
            "output_token_count": 50,
            "total_token_count": 150,
        }
        context = mock.MagicMock()
        context.messages = [mock.MagicMock(text="hello")]
        context.result = result
        context.metadata = {}

        await mw.process(context, call_next)
