"""Tests for src.utils.errors — error message extraction."""

from __future__ import annotations

from src.utils.errors import get_error_message, get_safe_client_message
from src.utils.url import UnsafeURLError


class TestGetErrorMessage:
    """Tests for get_error_message()."""

    def test_exception_with_message(self) -> None:
        assert get_error_message(ValueError("something broke")) == "something broke"

    def test_exception_without_message(self) -> None:
        assert get_error_message(ValueError()) == "ValueError"

    def test_runtime_error(self) -> None:
        assert get_error_message(RuntimeError("runtime issue")) == "runtime issue"

    def test_type_error(self) -> None:
        assert get_error_message(TypeError("bad type")) == "bad type"

    def test_custom_exception(self) -> None:
        class CustomError(Exception):
            pass

        assert get_error_message(CustomError("custom")) == "custom"


class TestGetSafeClientMessage:
    """Tests for get_safe_client_message()."""

    def test_generic_exception_returns_safe_message(self) -> None:
        result = get_safe_client_message(RuntimeError("/home/user/.config/secrets.yaml"))
        assert "internal error" in result.lower()
        assert "secrets" not in result

    def test_value_error_returns_safe_message(self) -> None:
        result = get_safe_client_message(ValueError("some internal detail"))
        assert "internal error" in result.lower()

    def test_unsafe_url_error_passes_through(self) -> None:
        msg = "Only http and https URLs are supported"
        result = get_safe_client_message(UnsafeURLError(msg))
        assert result == msg

    def test_timeout_error_passes_through(self) -> None:
        result = get_safe_client_message(TimeoutError("timed out"))
        assert result == "timed out"
