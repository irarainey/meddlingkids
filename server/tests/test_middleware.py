"""Tests for agent middleware utilities.

Covers ``_is_retryable``, ``EmptyResponseError``, and
``RetryChatMiddleware._get_retry_after``.
"""

from __future__ import annotations

import pytest

from src.agents.middleware import (
    EmptyResponseError,
    RetryChatMiddleware,
    _is_retryable,
)


# ── _is_retryable ──────────────────────────────────────────────


class TestIsRetryable:
    """Tests for the error classification helper."""

    def test_rate_limit_429_string(self) -> None:
        assert _is_retryable(Exception("Error 429 Too Many Requests"))

    def test_rate_limit_text(self) -> None:
        assert _is_retryable(Exception("rate limit exceeded"))

    def test_timeout_string(self) -> None:
        assert _is_retryable(Exception("connection timed out"))

    def test_timeout_error_type(self) -> None:
        assert _is_retryable(TimeoutError("timed out"))

    def test_connection_error_type(self) -> None:
        assert _is_retryable(ConnectionError("reset"))

    def test_connection_reset_error_type(self) -> None:
        assert _is_retryable(ConnectionResetError("peer reset"))

    def test_empty_response_error(self) -> None:
        assert _is_retryable(EmptyResponseError("empty"))

    def test_server_error_status_code(self) -> None:
        exc = Exception("server error")
        exc.status_code = 502  # type: ignore[attr-defined]
        assert _is_retryable(exc)

    def test_server_error_status_attr(self) -> None:
        exc = Exception("bad gateway")
        exc.status = 503  # type: ignore[attr-defined]
        assert _is_retryable(exc)

    def test_non_retryable_error(self) -> None:
        assert not _is_retryable(ValueError("invalid input"))

    def test_non_retryable_400(self) -> None:
        exc = Exception("bad request")
        exc.status_code = 400  # type: ignore[attr-defined]
        assert not _is_retryable(exc)


# ── EmptyResponseError ──────────────────────────────────────────


class TestEmptyResponseError:
    """Tests for EmptyResponseError."""

    def test_is_exception(self) -> None:
        assert isinstance(EmptyResponseError("test"), Exception)

    def test_message(self) -> None:
        err = EmptyResponseError("Agent X got nothing")
        assert "Agent X" in str(err)


# ── _get_retry_after ────────────────────────────────────────────


class TestGetRetryAfter:
    """Tests for RetryChatMiddleware._get_retry_after."""

    def test_no_headers_attribute(self) -> None:
        assert RetryChatMiddleware._get_retry_after(Exception("oops")) is None

    def test_dict_with_retry_after(self) -> None:
        exc = Exception("rate limit")
        exc.headers = {"Retry-After": "5"}  # type: ignore[attr-defined]
        result = RetryChatMiddleware._get_retry_after(exc)
        assert result == 5000  # 5 seconds → 5000 ms

    def test_dict_with_lowercase_key(self) -> None:
        exc = Exception("rate limit")
        exc.headers = {"retry-after": "10"}  # type: ignore[attr-defined]
        result = RetryChatMiddleware._get_retry_after(exc)
        assert result == 10000

    def test_non_numeric_value(self) -> None:
        exc = Exception("rate limit")
        exc.headers = {"Retry-After": "Thu, 01 Jan 2099 00:00:00 GMT"}  # type: ignore[attr-defined]
        result = RetryChatMiddleware._get_retry_after(exc)
        assert result is None

    def test_non_dict_headers(self) -> None:
        exc = Exception("oops")
        exc.headers = "not a dict"  # type: ignore[attr-defined]
        result = RetryChatMiddleware._get_retry_after(exc)
        assert result is None
