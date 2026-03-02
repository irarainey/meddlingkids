"""Tests for src.utils.serialization — snake_to_camel conversion."""

from __future__ import annotations

import pytest

from src.utils.serialization import snake_to_camel


class TestSnakeToCamel:
    """Tests for snake_to_camel()."""

    @pytest.mark.parametrize(
        ("input_str", "expected"),
        [
            ("my_field_name", "myFieldName"),
            ("single", "single"),
            ("already_camel", "alreadyCamel"),
            ("a_b_c", "aBC"),
            ("has_manage_options", "hasManageOptions"),
            ("is_third_party", "isThirdParty"),
            ("http_only", "httpOnly"),
            ("same_site", "sameSite"),
            ("pre_consent", "preConsent"),
        ],
    )
    def test_conversion(self, input_str: str, expected: str) -> None:
        assert snake_to_camel(input_str) == expected

    def test_no_underscores(self) -> None:
        assert snake_to_camel("name") == "name"

    def test_empty_string(self) -> None:
        assert snake_to_camel("") == ""
