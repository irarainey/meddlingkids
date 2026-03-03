"""Tests for agent middleware utilities.

Covers ``_is_retryable``, ``EmptyResponseError``,
``RetryChatMiddleware._get_retry_after``, per-call timeout
error messages, and global LLM concurrency limiting.
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest

from src.agents import middleware as middleware_mod

# ── _is_retryable ──────────────────────────────────────────────


class TestIsRetryable:
    """Tests for the error classification helper."""

    def test_rate_limit_429_string(self) -> None:
        assert middleware_mod._is_retryable(Exception("Error 429 Too Many Requests"))

    def test_rate_limit_text(self) -> None:
        assert middleware_mod._is_retryable(Exception("rate limit exceeded"))

    def test_timeout_string(self) -> None:
        assert middleware_mod._is_retryable(Exception("connection timed out"))

    def test_timeout_error_type(self) -> None:
        assert middleware_mod._is_retryable(TimeoutError("timed out"))

    def test_connection_error_type(self) -> None:
        assert middleware_mod._is_retryable(ConnectionError("reset"))

    def test_connection_reset_error_type(self) -> None:
        # ConnectionResetError is a subclass of ConnectionError
        assert middleware_mod._is_retryable(ConnectionResetError("peer reset"))

    def test_empty_response_error(self) -> None:
        assert middleware_mod._is_retryable(middleware_mod.EmptyResponseError("empty"))

    def test_server_error_status_code(self) -> None:
        exc = Exception("server error")
        exc.status_code = 502  # type: ignore[attr-defined]
        assert middleware_mod._is_retryable(exc)

    def test_server_error_status_attr(self) -> None:
        exc = Exception("bad gateway")
        exc.status = 503  # type: ignore[attr-defined]
        assert middleware_mod._is_retryable(exc)

    def test_non_retryable_error(self) -> None:
        assert not middleware_mod._is_retryable(ValueError("invalid input"))

    def test_non_retryable_400(self) -> None:
        exc = Exception("bad request")
        exc.status_code = 400  # type: ignore[attr-defined]
        assert not middleware_mod._is_retryable(exc)


# ── EmptyResponseError ──────────────────────────────────────────


class TestEmptyResponseError:
    """Tests for EmptyResponseError."""

    def test_is_exception(self) -> None:
        assert isinstance(middleware_mod.EmptyResponseError("test"), Exception)

    def test_message(self) -> None:
        err = middleware_mod.EmptyResponseError("Agent X got nothing")
        assert "Agent X" in str(err)


# ── _get_retry_after ────────────────────────────────────────────


class TestGetRetryAfter:
    """Tests for RetryChatMiddleware._get_retry_after."""

    def test_no_headers_attribute(self) -> None:
        assert middleware_mod.RetryChatMiddleware._get_retry_after(Exception("oops")) is None

    def test_dict_with_retry_after(self) -> None:
        exc = Exception("rate limit")
        exc.headers = {"Retry-After": "5"}  # type: ignore[attr-defined]
        result = middleware_mod.RetryChatMiddleware._get_retry_after(exc)
        assert result == 5000  # 5 seconds → 5000 ms

    def test_dict_with_lowercase_key(self) -> None:
        exc = Exception("rate limit")
        exc.headers = {"retry-after": "10"}  # type: ignore[attr-defined]
        result = middleware_mod.RetryChatMiddleware._get_retry_after(exc)
        assert result == 10000

    def test_non_numeric_value(self) -> None:
        exc = Exception("rate limit")
        exc.headers = {"Retry-After": "Thu, 01 Jan 2099 00:00:00 GMT"}  # type: ignore[attr-defined]
        result = middleware_mod.RetryChatMiddleware._get_retry_after(exc)
        assert result is None

    def test_non_dict_headers(self) -> None:
        exc = Exception("oops")
        exc.headers = "not a dict"  # type: ignore[attr-defined]
        result = middleware_mod.RetryChatMiddleware._get_retry_after(exc)
        assert result is None


# ── Global LLM concurrency ─────────────────────────────────────


class TestGlobalLLMConcurrency:
    """Tests for the global LLM concurrency semaphore."""

    def test_semaphore_exists_with_expected_limit(self) -> None:
        assert middleware_mod._llm_semaphore._value == middleware_mod._MAX_CONCURRENT_LLM_CALLS

    def test_max_concurrent_llm_calls_value(self) -> None:
        assert middleware_mod._MAX_CONCURRENT_LLM_CALLS == 10


# ── Timeout error message ──────────────────────────────────────


class TestTimeoutErrorMessage:
    """Timeout errors should include a descriptive message."""

    @pytest.mark.asyncio
    async def test_timeout_raises_with_descriptive_message(self) -> None:
        """A per-call timeout wraps the bare TimeoutError."""
        middleware = middleware_mod.RetryChatMiddleware(
            "TestAgent",
            max_retries=0,
            per_call_timeout=5.0,
        )
        context = mock.MagicMock()
        context.result = None

        async def slow_next() -> None:
            await asyncio.sleep(999)

        with pytest.raises(TimeoutError, match=r"timed out after 5\.0s"):
            await middleware.process(context, slow_next)

    @pytest.mark.asyncio
    async def test_timeout_retried_then_raises(self) -> None:
        """Timeouts are retried up to max_retries, then raised."""
        call_count = 0

        async def slow_next() -> None:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(999)

        middleware = middleware_mod.RetryChatMiddleware(
            "TestAgent",
            max_retries=1,
            per_call_timeout=0.05,
            initial_delay_ms=10,
        )
        context = mock.MagicMock()
        context.result = None

        with pytest.raises(TimeoutError, match=r"timed out after 0\.05s"):
            await middleware.process(context, slow_next)

        assert call_count == 2  # initial + 1 retry


# ── Semaphore integration ──────────────────────────────────────


class TestSemaphoreIntegration:
    """The retry middleware should acquire the global semaphore."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self) -> None:
        """Only _MAX_CONCURRENT_LLM_CALLS should run at once."""
        peak_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def tracking_next() -> None:
            nonlocal peak_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                peak_concurrent = max(peak_concurrent, current_concurrent)
            await asyncio.sleep(0.05)
            async with lock:
                current_concurrent -= 1

        # Launch more tasks than the semaphore allows.
        total = middleware_mod._MAX_CONCURRENT_LLM_CALLS + 4
        middlewares = [middleware_mod.RetryChatMiddleware(f"Agent-{i}", max_retries=0) for i in range(total)]
        contexts = [mock.MagicMock() for _ in range(total)]
        for ctx in contexts:
            ctx.result = None

        await asyncio.gather(*(m.process(ctx, tracking_next) for m, ctx in zip(middlewares, contexts, strict=True)))
        assert peak_concurrent <= middleware_mod._MAX_CONCURRENT_LLM_CALLS

    @pytest.mark.asyncio
    async def test_semaphore_released_on_success(self) -> None:
        """Semaphore is released after a successful call."""

        async def ok_next() -> None:
            pass

        middleware = middleware_mod.RetryChatMiddleware("TestAgent", max_retries=0)
        context = mock.MagicMock()
        context.result = None

        initial = middleware_mod._llm_semaphore._value
        await middleware.process(context, ok_next)
        assert middleware_mod._llm_semaphore._value == initial

    @pytest.mark.asyncio
    async def test_semaphore_released_on_failure(self) -> None:
        """Semaphore is released even when the call fails."""

        async def fail_next() -> None:
            raise ValueError("non-retryable")

        middleware = middleware_mod.RetryChatMiddleware("TestAgent", max_retries=0)
        context = mock.MagicMock()
        context.result = None

        initial = middleware_mod._llm_semaphore._value
        with pytest.raises(ValueError):
            await middleware.process(context, fail_next)
        assert middleware_mod._llm_semaphore._value == initial


# ── _describe_response ─────────────────────────────────────────


class TestDescribeResponse:
    """Tests for the LLM response metadata extractor."""

    def test_no_metadata_returns_fallback(self) -> None:
        result = object()
        assert middleware_mod._describe_response(result) == "(no metadata)"

    def test_finish_reason_only(self) -> None:
        result = mock.MagicMock(spec=[])
        result.finish_reason = "stop"
        result.model_id = None
        result.usage_details = None
        result.additional_properties = None
        desc = middleware_mod._describe_response(result)
        assert desc == "finish_reason=stop"

    def test_full_metadata(self) -> None:
        result = mock.MagicMock(spec=[])
        result.finish_reason = "length"
        result.model_id = "gpt-5.2-chat"
        result.usage_details = {
            "input_token_count": 50000,
            "output_token_count": 2048,
        }
        result.additional_properties = {"system_fingerprint": None}
        desc = middleware_mod._describe_response(result)
        assert "finish_reason=length" in desc
        assert "model=gpt-5.2-chat" in desc
        assert "input_tokens=50000" in desc
        assert "output_tokens=2048" in desc
        assert "extra=" in desc

    def test_usage_without_token_counts(self) -> None:
        result = mock.MagicMock(spec=[])
        result.finish_reason = "content_filter"
        result.model_id = None
        result.usage_details = {}
        result.additional_properties = None
        desc = middleware_mod._describe_response(result)
        assert desc == "finish_reason=content_filter"

    def test_model_id_without_finish_reason(self) -> None:
        result = mock.MagicMock(spec=[])
        result.finish_reason = None
        result.model_id = "gpt-5.2-chat"
        result.usage_details = None
        result.additional_properties = None
        desc = middleware_mod._describe_response(result)
        assert desc == "model=gpt-5.2-chat"

    def test_none_result(self) -> None:
        """None has no attributes — should return fallback."""
        assert middleware_mod._describe_response(None) == "(no metadata)"


# ── Empty response metadata ────────────────────────────────────


class TestEmptyResponseMetadata:
    """The empty response error should include LLM metadata."""

    @pytest.mark.asyncio
    async def test_empty_response_includes_metadata(self) -> None:
        """EmptyResponseError message contains finish_reason."""
        middleware = middleware_mod.RetryChatMiddleware(
            "TestAgent",
            max_retries=0,
        )
        context = mock.MagicMock()
        result = mock.MagicMock(spec=[])
        result.text = ""
        result.finish_reason = "content_filter"
        result.model_id = "gpt-5.2-chat"
        result.usage_details = {
            "input_token_count": 114000,
            "output_token_count": 0,
        }
        result.additional_properties = None
        context.result = result

        async def ok_next() -> None:
            pass

        with pytest.raises(middleware_mod.EmptyResponseError, match="finish_reason=content_filter"):
            await middleware.process(context, ok_next)
