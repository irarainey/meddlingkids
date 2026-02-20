"""Tests for src.consent.click — consent button click strategies.

Focuses on the safety-check bypass for cross-origin consent iframes
and the is_consent_frame parameter threading.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.consent import click

# ────────────────────────────────────────────────────────────
# _safe_click — skip_safety parameter
# ────────────────────────────────────────────────────────────


class TestSafeClickSkipSafety:
    """Verify _safe_click bypasses evaluate() when skip_safety=True."""

    @pytest.mark.asyncio
    async def test_skip_safety_true_clicks_without_evaluate(self) -> None:
        """When skip_safety=True, click directly without calling evaluate()."""
        locator = AsyncMock()
        first = AsyncMock()
        locator.first = first
        first.click = AsyncMock()
        first.evaluate = AsyncMock()

        result = await click._safe_click(locator, 3000, skip_safety=True)

        assert result is True
        first.click.assert_awaited_once_with(timeout=3000)
        first.evaluate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skip_safety_false_calls_evaluate(self) -> None:
        """When skip_safety=False (default), evaluate() is called."""
        locator = AsyncMock()
        first = AsyncMock()
        locator.first = first
        first.evaluate = AsyncMock(return_value=True)
        first.click = AsyncMock()

        result = await click._safe_click(locator, 3000, skip_safety=False)

        assert result is True
        first.evaluate.assert_awaited_once()
        first.click.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skip_safety_click_exception_returns_false(self) -> None:
        """When skip_safety=True but click fails, returns False."""
        locator = AsyncMock()
        first = AsyncMock()
        locator.first = first
        first.click = AsyncMock(side_effect=Exception("timeout"))

        result = await click._safe_click(locator, 3000, skip_safety=True)

        assert result is False

    @pytest.mark.asyncio
    async def test_default_skip_safety_is_false(self) -> None:
        """Default skip_safety is False — evaluate() is called."""
        locator = AsyncMock()
        first = AsyncMock()
        locator.first = first
        first.evaluate = AsyncMock(return_value=True)
        first.click = AsyncMock()

        await click._safe_click(locator, 3000)

        first.evaluate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_evaluate_returns_false_blocks_click(self) -> None:
        """When evaluate() says unsafe, click is not attempted."""
        locator = AsyncMock()
        first = AsyncMock()
        locator.first = first
        first.evaluate = AsyncMock(return_value=False)
        first.click = AsyncMock()

        result = await click._safe_click(locator, 3000)

        assert result is False
        first.click.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_evaluate_timeout_without_force_blocks_click(self) -> None:
        """When evaluate() times out and force_on_timeout=False, skip."""
        locator = AsyncMock()
        first = AsyncMock()
        locator.first = first
        first.evaluate = AsyncMock(side_effect=Exception("timeout"))
        first.click = AsyncMock()

        result = await click._safe_click(
            locator,
            3000,
            force_on_timeout=False,
        )

        assert result is False
        first.click.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_evaluate_timeout_with_force_clicks(self) -> None:
        """When evaluate() times out but force_on_timeout=True, click anyway."""
        locator = AsyncMock()
        first = AsyncMock()
        locator.first = first
        first.evaluate = AsyncMock(side_effect=Exception("timeout"))
        first.click = AsyncMock()

        result = await click._safe_click(
            locator,
            3000,
            force_on_timeout=True,
        )

        assert result is True
        first.click.assert_awaited_once()


# ────────────────────────────────────────────────────────────
# _try_click_in_frame — is_consent_frame parameter
# ────────────────────────────────────────────────────────────


class TestTryClickInFrameConsentFrame:
    """Verify _try_click_in_frame passes skip_safety for consent frames."""

    @pytest.mark.asyncio
    async def test_consent_frame_passes_skip_safety(self) -> None:
        """When is_consent_frame=True, _safe_click receives skip_safety=True."""
        frame = MagicMock()
        locator = AsyncMock()
        first = AsyncMock()
        locator.first = first
        first.click = AsyncMock()
        first_mock = MagicMock()
        first_mock.first = locator
        frame.get_by_role = MagicMock(return_value=first_mock)
        frame.get_by_text = MagicMock(return_value=first_mock)

        with patch.object(click, "_safe_click", new_callable=AsyncMock) as mock_safe:
            mock_safe.return_value = True
            result = await click._try_click_in_frame(
                frame,
                None,
                "Accept",
                3000,
                is_consent_frame=True,
            )

        assert result is not None
        # Verify skip_safety=True was passed
        _, kwargs = mock_safe.call_args
        assert kwargs.get("skip_safety") is True

    @pytest.mark.asyncio
    async def test_non_consent_frame_skip_safety_false(self) -> None:
        """When is_consent_frame=False (default), skip_safety=False."""
        frame = MagicMock()
        locator = AsyncMock()
        first = AsyncMock()
        locator.first = first
        first.click = AsyncMock()
        first_mock = MagicMock()
        first_mock.first = locator
        frame.get_by_role = MagicMock(return_value=first_mock)
        frame.get_by_text = MagicMock(return_value=first_mock)

        with patch.object(click, "_safe_click", new_callable=AsyncMock) as mock_safe:
            mock_safe.return_value = True
            result = await click._try_click_in_frame(
                frame,
                None,
                "Accept",
                3000,
                is_consent_frame=False,
            )

        assert result is not None
        _, kwargs = mock_safe.call_args
        assert kwargs.get("skip_safety") is False

    @pytest.mark.asyncio
    async def test_css_selector_inherits_consent_frame(self) -> None:
        """CSS selector strategy also gets skip_safety from is_consent_frame."""
        frame = MagicMock()
        locator = AsyncMock()
        first = AsyncMock()
        locator.first = first
        first.click = AsyncMock()
        first_mock = MagicMock()
        first_mock.first = locator
        frame.locator = MagicMock(return_value=first_mock)

        with patch.object(click, "_safe_click", new_callable=AsyncMock) as mock_safe:
            mock_safe.return_value = True
            result = await click._try_click_in_frame(
                frame,
                "button.fc-cta-consent",
                None,
                3000,
                is_consent_frame=True,
            )

        assert result == "css"
        _, kwargs = mock_safe.call_args
        assert kwargs.get("skip_safety") is True


# ────────────────────────────────────────────────────────────
# _is_safe_to_click
# ────────────────────────────────────────────────────────────


class TestIsSafeToClick:
    """Verify _is_safe_to_click return values."""

    @pytest.mark.asyncio
    async def test_button_element_is_safe(self) -> None:
        """A <button> element returns True."""
        locator = AsyncMock()
        locator.evaluate = AsyncMock(return_value=True)

        result = await click._is_safe_to_click(locator)
        assert result is True

    @pytest.mark.asyncio
    async def test_real_link_is_unsafe(self) -> None:
        """An <a href="https://example.com"> returns False."""
        locator = AsyncMock()
        locator.evaluate = AsyncMock(return_value=False)

        result = await click._is_safe_to_click(locator)
        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self) -> None:
        """Cross-origin timeout returns None."""
        locator = AsyncMock()
        locator.evaluate = AsyncMock(side_effect=Exception("Timeout 2000ms"))

        result = await click._is_safe_to_click(locator)
        assert result is None


# ────────────────────────────────────────────────────────────
# ClickResult
# ────────────────────────────────────────────────────────────


class TestClickResult:
    """Verify ClickResult construction."""

    def test_failed_result(self) -> None:
        result = click.ClickResult(success=False)
        assert result.success is False
        assert result.strategy is None
        assert result.frame_type is None

    def test_success_result(self) -> None:
        result = click.ClickResult(
            success=True,
            strategy="css",
            frame_type="consent-iframe",
        )
        assert result.success is True
        assert result.strategy == "css"
        assert result.frame_type == "consent-iframe"
