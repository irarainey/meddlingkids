"""Tests for src.agents.context_providers — MAF ContextProviders."""

from __future__ import annotations

from unittest import mock

import agent_framework
import pytest

from src.agents import context_providers


class TestGdprReferenceProvider:
    """Validates GdprReferenceProvider context injection."""

    @pytest.fixture
    def provider(self) -> context_providers.GdprReferenceProvider:
        return context_providers.GdprReferenceProvider()

    @pytest.mark.asyncio
    async def test_injects_when_enabled(self, provider: context_providers.GdprReferenceProvider) -> None:
        """Provider injects GDPR reference when session state flag is set."""
        context = mock.MagicMock(spec=agent_framework.SessionContext)
        state: dict[str, object] = {context_providers.GDPR_CONTEXT_ENABLED_KEY: True}

        await provider.before_run(
            agent=mock.MagicMock(),
            session=mock.MagicMock(),
            context=context,
            state=state,
        )

        context.extend_instructions.assert_called_once()
        args = context.extend_instructions.call_args
        assert args[0][0] == "gdpr-reference"
        assert "GDPR" in args[0][1]

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self, provider: context_providers.GdprReferenceProvider) -> None:
        """Provider is a no-op when session state flag is not set."""
        context = mock.MagicMock(spec=agent_framework.SessionContext)
        state: dict[str, object] = {}

        await provider.before_run(
            agent=mock.MagicMock(),
            session=mock.MagicMock(),
            context=context,
            state=state,
        )

        context.extend_instructions.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_explicitly_false(self, provider: context_providers.GdprReferenceProvider) -> None:
        """Provider is a no-op when flag is explicitly False."""
        context = mock.MagicMock(spec=agent_framework.SessionContext)
        state: dict[str, object] = {context_providers.GDPR_CONTEXT_ENABLED_KEY: False}

        await provider.before_run(
            agent=mock.MagicMock(),
            session=mock.MagicMock(),
            context=context,
            state=state,
        )

        context.extend_instructions.assert_not_called()

    def test_source_id(self, provider: context_providers.GdprReferenceProvider) -> None:
        """Provider has the expected source_id."""
        assert provider.source_id == "gdpr-reference"
