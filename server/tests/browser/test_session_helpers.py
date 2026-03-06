"""Tests for src.browser.session — pure utility functions."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from src.browser.session import BrowserSession, _is_non_script_url


class TestIsNonScriptUrl:
    """Tests for _is_non_script_url()."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://example.com/style.css", True),
            ("https://example.com/image.png", True),
            ("https://example.com/data.json", True),
            ("https://example.com/font.woff2", True),
            ("https://example.com/photo.jpg", True),
            ("https://example.com/photo.jpeg", True),
            ("https://example.com/icon.ico", True),
            ("https://example.com/image.gif", True),
            ("https://example.com/image.webp", True),
            ("https://example.com/image.svg", True),
            ("https://example.com/font.eot", True),
            ("https://example.com/script.js", False),
            ("https://example.com/api/data", False),
            ("https://example.com/", False),
            ("https://example.com/data.json?callback=cb", True),
            ("https://example.com/style.css#section", True),
        ],
    )
    def test_extension_detection(self, url: str, expected: bool) -> None:
        assert _is_non_script_url(url) is expected

    def test_no_extension(self) -> None:
        assert _is_non_script_url("https://example.com/api/data") is False


class TestOptimizeScreenshotBytes:
    """Tests for BrowserSession.optimize_screenshot_bytes()."""

    def test_empty_bytes_returns_empty_string(self) -> None:
        result = BrowserSession.optimize_screenshot_bytes(b"")
        assert result == ""

    def test_produces_data_url(self) -> None:
        img = Image.new("RGB", (100, 50), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        img.close()
        result = BrowserSession.optimize_screenshot_bytes(buf.getvalue())
        assert result.startswith("data:image/jpeg;base64,")
