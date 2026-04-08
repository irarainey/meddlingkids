"""Storage key information agent for LLM-based identification.

Analyses individual browser storage keys (localStorage/sessionStorage)
to determine their purpose, the service that sets them, and their
privacy implications.  Falls back to LLM only when the key is not
found in the known storage-key pattern database.
"""

from __future__ import annotations

from src.agents import base, config
from src.agents.prompts import storage_info
from src.models import item_info

# ── Structured output model ─────────────────────────────────────


class StorageInfoResult(item_info.ItemInfoResult):
    """LLM response describing a single storage key."""


# ── Agent class ─────────────────────────────────────────────────


class StorageInfoAgent(base.BaseAgent):
    """Text agent that explains a single storage key.

    Receives a storage key name, type, and value and returns
    a structured explanation of what the key does.
    """

    agent_name = config.AGENT_STORAGE_INFO
    instructions = storage_info.INSTRUCTIONS
    max_tokens = 300
    max_retries = 2
    response_model = StorageInfoResult

    async def explain(
        self,
        key: str,
        storage_type: str,
        value: str,
    ) -> StorageInfoResult | None:
        """Explain a single storage key via LLM.

        Args:
            key: Storage key name.
            storage_type: Type of storage ("localStorage" or "sessionStorage").
            value: Key value (truncated for the prompt).

        Returns:
            Structured storage key information, or ``None`` on failure.
        """
        truncated_value = value[:200] if value else "[empty]"
        user_message = f"Storage key: {key}\nType: {storage_type}\nValue: {truncated_value}"

        return await self._explain_item(
            user_message,
            StorageInfoResult,
            log_label="storage info",
            log_context={"key": key, "type": storage_type},
        )
