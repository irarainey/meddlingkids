"""Extended tests for agent middleware — timing, response description, and helpers."""

from __future__ import annotations

from unittest import mock

import pytest

from src.agents import middleware


class TestEstimateMessageChars:
    """Tests for _estimate_message_chars()."""

    def test_empty_list(self) -> None:
        assert middleware._estimate_message_chars([]) == 0

    def test_messages_with_text(self) -> None:
        msg1 = mock.MagicMock()
        msg1.text = "Hello, world!"
        msg2 = mock.MagicMock()
        msg2.text = "How are you?"
        assert middleware._estimate_message_chars([msg1, msg2]) == 25

    def test_messages_without_text(self) -> None:
        msg = mock.MagicMock(spec=[])
        assert middleware._estimate_message_chars([msg]) == 0

    def test_message_with_none_text(self) -> None:
        msg = mock.MagicMock()
        msg.text = None
        assert middleware._estimate_message_chars([msg]) == 0


class TestDescribeResponse:
    """Tests for _describe_response()."""

    def test_none_result(self) -> None:
        assert middleware._describe_response(None) == "(no metadata)"

    def test_with_finish_reason(self) -> None:
        result = mock.MagicMock(spec=["finish_reason"])
        result.finish_reason = "stop"
        desc = middleware._describe_response(result)
        assert "finish_reason=stop" in desc

    def test_with_model(self) -> None:
        result = mock.MagicMock(spec=["model"])
        result.model = "gpt-4o"
        desc = middleware._describe_response(result)
        assert "model=gpt-4o" in desc

    def test_with_usage_details(self) -> None:
        result = mock.MagicMock(spec=["usage_details"])
        result.usage_details = {"input_token_count": 100, "output_token_count": 50}
        desc = middleware._describe_response(result)
        assert "input_tokens=100" in desc
        assert "output_tokens=50" in desc

    def test_with_additional_properties(self) -> None:
        result = mock.MagicMock(spec=["additional_properties"])
        result.additional_properties = {"key": "value"}
        desc = middleware._describe_response(result)
        assert "extra=" in desc

    def test_with_all_fields(self) -> None:
        result = mock.MagicMock()
        result.finish_reason = "stop"
        result.model = "gpt-4o"
        result.usage_details = {"input_token_count": 1000, "output_token_count": 500}
        result.additional_properties = None
        desc = middleware._describe_response(result)
        assert "finish_reason=stop" in desc
        assert "model=gpt-4o" in desc


class TestOutputTruncatedError:
    """Tests for OutputTruncatedError."""

    def test_is_subclass_of_empty_response(self) -> None:
        assert issubclass(middleware.OutputTruncatedError, middleware.EmptyResponseError)

    def test_not_retryable(self) -> None:
        assert not middleware._is_retryable(middleware.OutputTruncatedError("truncated"))

    def test_message(self) -> None:
        err = middleware.OutputTruncatedError("Agent X output exceeded max_tokens")
        assert "max_tokens" in str(err)


class TestTimingChatMiddleware:
    """Tests for TimingChatMiddleware initialization."""

    def test_default_agent_name(self) -> None:
        mw = middleware.TimingChatMiddleware()
        assert mw.agent_name == "Unknown"

    def test_custom_agent_name(self) -> None:
        mw = middleware.TimingChatMiddleware("MyAgent")
        assert mw.agent_name == "MyAgent"

    @pytest.mark.asyncio
    async def test_process_completes_without_error(self) -> None:
        mw = middleware.TimingChatMiddleware("TestAgent")

        async def call_next() -> None:
            pass

        context = mock.MagicMock()
        context.messages = []
        context.result = None

        await mw.process(context, call_next)

    @pytest.mark.asyncio
    async def test_records_usage_without_details(self) -> None:
        mw = middleware.TimingChatMiddleware("TestAgent")

        async def call_next() -> None:
            pass

        result = mock.MagicMock(spec=[])  # No usage_details
        context = mock.MagicMock()
        context.messages = []
        context.result = result

        await mw.process(context, call_next)

    @pytest.mark.asyncio
    async def test_records_usage_with_details(self) -> None:
        mw = middleware.TimingChatMiddleware("TestAgent")

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

        await mw.process(context, call_next)
