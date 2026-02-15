"""Tests for src.utils.errors — error message extraction."""

from __future__ import annotations

from src.utils.errors import get_error_message


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
