"""Tests for src.pipeline.overlay_steps — overlay helpers and detection."""

from __future__ import annotations

import asyncio
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from src.models import consent
from src.pipeline.overlay_steps import detect_overlay, get_overlay_message


def _make_jpeg(
    width: int = 800,
    height: int = 600,
    color: str = "blue",
) -> bytes:
    """Create a minimal JPEG image in memory."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=72)
    return buf.getvalue()


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Return (width, height) of JPEG bytes."""
    img = Image.open(io.BytesIO(data))
    return img.width, img.height


class TestGetOverlayMessage:
    @pytest.mark.parametrize(
        ("overlay_type", "expected"),
        [
            ("cookie-consent", "Cookie consent detected"),
            ("sign-in", "Sign-in prompt detected"),
            ("newsletter", "Newsletter popup detected"),
            ("paywall", "Paywall detected"),
            ("age-verification", "Age verification detected"),
        ],
    )
    def test_known_types(self, overlay_type: str, expected: str) -> None:
        assert get_overlay_message(overlay_type) == expected

    def test_unknown_type(self) -> None:
        assert get_overlay_message("something-else") == "Overlay detected"

    def test_none_type(self) -> None:
        assert get_overlay_message(None) == "Overlay detected"


# ────────────────────────────────────────────────────────────
# detect_overlay — speculative cropping for content filters
# ────────────────────────────────────────────────────────────


class TestDetectOverlayCropping:
    """Verify that detect_overlay crops to consent dialog
    bounds when available, preventing content-filter issues.
    """

    @pytest.fixture()
    def viewport_jpeg(self) -> bytes:
        """An 800×600 viewport screenshot."""
        return _make_jpeg(800, 600)

    @pytest.fixture()
    def session(self, viewport_jpeg: bytes) -> MagicMock:
        """Mock browser session with page and screenshot."""
        page = AsyncMock()
        session = MagicMock()
        session.take_screenshot = AsyncMock(
            return_value=viewport_jpeg,
        )
        session.get_page.return_value = page
        return session

    @pytest.mark.asyncio()
    async def test_crops_when_bounds_found(
        self,
        session: MagicMock,
        viewport_jpeg: bytes,
    ) -> None:
        """When JS finds consent bounds, the screenshot sent
        to the detection agent should be cropped."""
        # Consent dialog at (100, 200, 700, 500).
        page = session.get_page()
        page.evaluate = AsyncMock(
            return_value={
                "left": 100,
                "top": 200,
                "right": 700,
                "bottom": 500,
            },
        )

        sent_bytes: list[bytes] = []

        async def fake_detect(screenshot: bytes) -> consent.CookieConsentDetection:
            sent_bytes.append(screenshot)
            return consent.CookieConsentDetection.not_found("test")

        with patch(
            "src.consent.detection.detect_cookie_consent",
            side_effect=fake_detect,
        ):
            await detect_overlay(session, 0)

        assert len(sent_bytes) == 1
        # The sent screenshot should be smaller than the
        # full viewport — it was cropped.
        assert len(sent_bytes[0]) < len(viewport_jpeg)
        w, h = _jpeg_dimensions(sent_bytes[0])
        assert w == 600  # 700 - 100
        assert h == 300  # 500 - 200

    @pytest.mark.asyncio()
    async def test_uses_full_screenshot_when_no_bounds(
        self,
        session: MagicMock,
        viewport_jpeg: bytes,
    ) -> None:
        """When JS returns null (no dialog found), the full
        viewport screenshot is sent."""
        page = session.get_page()
        page.evaluate = AsyncMock(return_value=None)

        sent_bytes: list[bytes] = []

        async def fake_detect(screenshot: bytes) -> consent.CookieConsentDetection:
            sent_bytes.append(screenshot)
            return consent.CookieConsentDetection.not_found("test")

        with patch(
            "src.consent.detection.detect_cookie_consent",
            side_effect=fake_detect,
        ):
            await detect_overlay(session, 0)

        assert len(sent_bytes) == 1
        assert sent_bytes[0] == viewport_jpeg

    @pytest.mark.asyncio()
    async def test_falls_back_on_evaluate_error(
        self,
        session: MagicMock,
        viewport_jpeg: bytes,
    ) -> None:
        """When page.evaluate() throws, the full screenshot
        is sent as a fallback."""
        page = session.get_page()
        page.evaluate = AsyncMock(
            side_effect=Exception("Frame detached"),
        )

        sent_bytes: list[bytes] = []

        async def fake_detect(screenshot: bytes) -> consent.CookieConsentDetection:
            sent_bytes.append(screenshot)
            return consent.CookieConsentDetection.not_found("test")

        with patch(
            "src.consent.detection.detect_cookie_consent",
            side_effect=fake_detect,
        ):
            await detect_overlay(session, 0)

        assert len(sent_bytes) == 1
        assert sent_bytes[0] == viewport_jpeg

    @pytest.mark.asyncio()
    async def test_falls_back_when_page_is_none(
        self,
        viewport_jpeg: bytes,
    ) -> None:
        """When session.get_page() returns None, cropping
        is skipped and the full screenshot is sent."""
        session = MagicMock()
        session.take_screenshot = AsyncMock(
            return_value=viewport_jpeg,
        )
        session.get_page.return_value = None

        sent_bytes: list[bytes] = []

        async def fake_detect(screenshot: bytes) -> consent.CookieConsentDetection:
            sent_bytes.append(screenshot)
            return consent.CookieConsentDetection.not_found("test")

        with patch(
            "src.consent.detection.detect_cookie_consent",
            side_effect=fake_detect,
        ):
            await detect_overlay(session, 0)

        assert len(sent_bytes) == 1
        assert sent_bytes[0] == viewport_jpeg

    @pytest.mark.asyncio()
    async def test_invalid_bounds_sends_full_screenshot(
        self,
        session: MagicMock,
        viewport_jpeg: bytes,
    ) -> None:
        """When bounds are invalid (zero-area), crop_jpeg
        returns the original and the full screenshot is sent."""
        page = session.get_page()
        # Zero-width box — crop_jpeg returns original.
        page.evaluate = AsyncMock(
            return_value={
                "left": 500,
                "top": 200,
                "right": 500,
                "bottom": 400,
            },
        )

        sent_bytes: list[bytes] = []

        async def fake_detect(screenshot: bytes) -> consent.CookieConsentDetection:
            sent_bytes.append(screenshot)
            return consent.CookieConsentDetection.not_found("test")

        with patch(
            "src.consent.detection.detect_cookie_consent",
            side_effect=fake_detect,
        ):
            await detect_overlay(session, 0)

        # crop_jpeg returns original for invalid box, so
        # identity check fails → no crop applied.
        assert len(sent_bytes) == 1
        assert sent_bytes[0] == viewport_jpeg