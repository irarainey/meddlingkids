"""Tests for src.utils.image — screenshot optimization."""

from __future__ import annotations

import io

from PIL import Image

from src.utils.image import optimize_for_llm, optimize_png_to_jpeg, png_to_data_url


def _make_png(width: int = 200, height: int = 100, color: str = "red") -> bytes:
    """Create a minimal PNG image in memory."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_rgba_png(width: int = 200, height: int = 100) -> bytes:
    """Create a minimal RGBA PNG image in memory."""
    img = Image.new("RGBA", (width, height), (255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestOptimizePngToJpeg:
    """Tests for optimize_png_to_jpeg()."""

    def test_converts_png_to_jpeg(self) -> None:
        png = _make_png()
        jpeg_bytes, w, h = optimize_png_to_jpeg(png)
        assert jpeg_bytes[:2] == b"\xff\xd8"  # JPEG magic bytes
        assert w == 200
        assert h == 100

    def test_downscales_large_image(self) -> None:
        png = _make_png(width=2048, height=1024)
        _, w, h = optimize_png_to_jpeg(png, max_width=1280)
        assert w == 1280
        assert h == 640

    def test_does_not_upscale_small_image(self) -> None:
        png = _make_png(width=100, height=50)
        _, w, h = optimize_png_to_jpeg(png, max_width=1280)
        assert w == 100
        assert h == 50

    def test_handles_rgba_input(self) -> None:
        png = _make_rgba_png()
        jpeg_bytes, w, h = optimize_png_to_jpeg(png)
        assert jpeg_bytes[:2] == b"\xff\xd8"
        assert w == 200
        assert h == 100

    def test_custom_max_width(self) -> None:
        png = _make_png(width=1600, height=900)
        _, w, _h = optimize_png_to_jpeg(png, max_width=800)
        assert w == 800

    def test_custom_quality(self) -> None:
        png = _make_png(width=200, height=100)
        low_q, _, _ = optimize_png_to_jpeg(png, quality=10)
        high_q, _, _ = optimize_png_to_jpeg(png, quality=95)
        # Lower quality should produce smaller output
        assert len(low_q) < len(high_q)


class TestPngToDataUrl:
    """Tests for png_to_data_url()."""

    def test_returns_data_url(self) -> None:
        png = _make_png()
        result = png_to_data_url(png)
        assert result.startswith("data:image/jpeg;base64,")

    def test_data_url_is_valid_base64(self) -> None:
        import base64

        png = _make_png()
        result = png_to_data_url(png)
        b64_data = result.split(",", 1)[1]
        # Should not raise
        decoded = base64.b64decode(b64_data)
        assert decoded[:2] == b"\xff\xd8"


class TestOptimizeForLlm:
    """Tests for optimize_for_llm()."""

    def test_returns_data_url_and_size(self) -> None:
        png = _make_png(width=1600, height=900)
        data_url, byte_count = optimize_for_llm(png)
        assert data_url.startswith("data:image/jpeg;base64,")
        assert byte_count > 0

    def test_llm_downscales_more_aggressively(self) -> None:
        png = _make_png(width=2048, height=1024)
        _llm_url, llm_bytes = optimize_for_llm(png)
        client_bytes, _, _ = optimize_png_to_jpeg(png)
        # LLM version uses smaller max_width + lower quality
        assert llm_bytes < len(client_bytes)
