"""Tests for src.utils.image — screenshot optimization."""

from __future__ import annotations

import io

from PIL import Image

from src.utils.image import downscale_jpeg, optimize_for_llm, screenshot_to_data_url


def _make_jpeg(width: int = 200, height: int = 100, color: str = "red", quality: int = 72) -> bytes:
    """Create a minimal JPEG image in memory."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


class TestDownscaleJpeg:
    """Tests for downscale_jpeg()."""

    def test_returns_jpeg(self) -> None:
        jpeg = _make_jpeg()
        out_bytes, w, h = downscale_jpeg(jpeg)
        assert out_bytes[:2] == b"\xff\xd8"  # JPEG magic bytes
        assert w == 200
        assert h == 100

    def test_passthrough_when_small(self) -> None:
        """Images within max_width are returned as-is (no re-encode)."""
        jpeg = _make_jpeg()
        out_bytes, w, h = downscale_jpeg(jpeg, max_width=1280)
        # Should be identical bytes — no re-encoding occurred
        assert out_bytes == jpeg
        assert w == 200
        assert h == 100

    def test_downscales_large_image(self) -> None:
        jpeg = _make_jpeg(width=2048, height=1024)
        _, w, h = downscale_jpeg(jpeg, max_width=1280)
        assert w == 1280
        assert h == 640

    def test_does_not_upscale_small_image(self) -> None:
        jpeg = _make_jpeg(width=100, height=50)
        _, w, h = downscale_jpeg(jpeg, max_width=1280)
        assert w == 100
        assert h == 50

    def test_custom_max_width(self) -> None:
        jpeg = _make_jpeg(width=1600, height=900)
        _, w, _h = downscale_jpeg(jpeg, max_width=800)
        assert w == 800

    def test_custom_quality_forces_reencode(self) -> None:
        jpeg = _make_jpeg(width=200, height=100, quality=95)
        low_q, _, _ = downscale_jpeg(jpeg, quality=10)
        high_q, _, _ = downscale_jpeg(jpeg, quality=95)
        # Lower quality should produce smaller output
        assert len(low_q) < len(high_q)


class TestScreenshotToDataUrl:
    """Tests for screenshot_to_data_url()."""

    def test_returns_data_url(self) -> None:
        jpeg = _make_jpeg()
        result = screenshot_to_data_url(jpeg)
        assert result.startswith("data:image/jpeg;base64,")

    def test_data_url_is_valid_base64(self) -> None:
        import base64

        jpeg = _make_jpeg()
        result = screenshot_to_data_url(jpeg)
        b64_data = result.split(",", 1)[1]
        # Should not raise
        decoded = base64.b64decode(b64_data)
        assert decoded[:2] == b"\xff\xd8"


class TestOptimizeForLlm:
    """Tests for optimize_for_llm()."""

    def test_returns_data_url_and_size(self) -> None:
        jpeg = _make_jpeg(width=1600, height=900)
        data_url, byte_count = optimize_for_llm(jpeg)
        assert data_url.startswith("data:image/jpeg;base64,")
        assert byte_count > 0

    def test_llm_downscales_more_aggressively(self) -> None:
        jpeg = _make_jpeg(width=2048, height=1024)
        _llm_url, llm_bytes = optimize_for_llm(jpeg)
        client_bytes, _, _ = downscale_jpeg(jpeg)
        # LLM version uses smaller max_width + lower quality
        assert llm_bytes < len(client_bytes)
