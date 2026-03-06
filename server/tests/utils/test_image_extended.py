"""Extended tests for src.utils.image — crop and LLM optimization."""

from __future__ import annotations

import io

from PIL import Image

from src.utils.image import crop_jpeg, optimize_for_llm


def _create_test_jpeg(width: int = 200, height: int = 100) -> bytes:
    """Create a minimal JPEG image for testing."""
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    img.close()
    return buf.getvalue()


class TestCropJpeg:
    """Tests for crop_jpeg()."""

    def test_valid_crop(self) -> None:
        jpeg = _create_test_jpeg(200, 100)
        cropped = crop_jpeg(jpeg, (10, 10, 100, 80))
        assert cropped != jpeg
        img = Image.open(io.BytesIO(cropped))
        assert img.width == 90
        assert img.height == 70
        img.close()

    def test_invalid_crop_returns_original(self) -> None:
        jpeg = _create_test_jpeg(200, 100)
        result = crop_jpeg(jpeg, (100, 50, 10, 5))
        assert result == jpeg

    def test_crop_clamped_to_bounds(self) -> None:
        jpeg = _create_test_jpeg(200, 100)
        cropped = crop_jpeg(jpeg, (-10, -10, 300, 200))
        img = Image.open(io.BytesIO(cropped))
        assert img.width == 200
        assert img.height == 100
        img.close()


class TestOptimizeForLlm:
    """Tests for optimize_for_llm()."""

    def test_produces_data_url(self) -> None:
        jpeg = _create_test_jpeg(800, 400)
        data_url, size = optimize_for_llm(jpeg)
        assert data_url.startswith("data:image/jpeg;base64,")
        assert size > 0

    def test_large_image_downscaled(self) -> None:
        jpeg = _create_test_jpeg(2000, 1000)
        data_url, _size = optimize_for_llm(jpeg)
        assert data_url.startswith("data:image/jpeg;base64,")

    def test_with_crop_box(self) -> None:
        jpeg = _create_test_jpeg(800, 600)
        data_url, _size = optimize_for_llm(jpeg, crop_box=(0, 0, 400, 300))
        assert data_url.startswith("data:image/jpeg;base64,")
