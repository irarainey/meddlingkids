"""MAF context providers for agent enrichment.

Provides reusable ``ContextProvider`` subclasses that inject
supplementary reference data into agent conversations via the
MAF ``before_run`` hook.  This replaces manual context-string
assembly for data that is static or semi-static across calls.
"""

from __future__ import annotations

import functools
from typing import Any

import agent_framework

from src.agents import gdpr_context
from src.utils import logger

log = logger.create_logger("ContextProviders")

# ── Session-state key used to gate GDPR injection ──────────────
GDPR_CONTEXT_ENABLED_KEY = "gdpr_context_enabled"


@functools.lru_cache(maxsize=1)
def _cached_gdpr_reference() -> str:
    """Load and cache the GDPR/TCF reference text.

    The reference data is loaded from static JSON files and
    never changes at runtime, so it is safe to cache
    indefinitely.
    """
    return gdpr_context.build_gdpr_reference(
        heading="## GDPR / TCF Reference Data",
    )


class GdprReferenceProvider(agent_framework.ContextProvider):
    """Injects GDPR/TCF regulatory reference into agent context.

    The GDPR/TCF reference data (lawful bases, TCF purposes,
    consent-cookie names, ePrivacy categories) is loaded once
    from static data files and cached.  It is injected as
    supplementary system instructions before each agent call
    where GDPR context is needed.

    Gate injection per-call by setting the session-state key
    ``gdpr_context_enabled`` to ``True`` before calling
    ``agent.run()``.  When the key is absent or ``False``,
    the provider is a no-op, keeping token usage low for
    calls that don't need regulatory context.
    """

    def __init__(self) -> None:
        super().__init__(source_id="gdpr-reference")

    async def before_run(
        self,
        *,
        agent: agent_framework.SupportsAgentRun,
        session: agent_framework.AgentSession,
        context: agent_framework.SessionContext,
        state: dict[str, Any],
    ) -> None:
        """Inject GDPR reference if enabled in session state."""
        if not state.get(GDPR_CONTEXT_ENABLED_KEY, False):
            return

        reference = _cached_gdpr_reference()
        if reference:
            context.extend_instructions(self.source_id, reference)
