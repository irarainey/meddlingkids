"""Storage key information agent for LLM-based identification.

Analyses individual browser storage keys (localStorage/sessionStorage)
to determine their purpose, the service that sets them, and their
privacy implications.  Falls back to LLM only when the key is not
found in the known storage-key pattern database.
"""

from __future__ import annotations

import pydantic

from src.agents import base, config
from src.agents.prompts import storage_info
from src.utils import json_parsing, logger

log = logger.create_logger("StorageInfoAgent")


# ── Structured output model ─────────────────────────────────────


class StorageInfoResult(pydantic.BaseModel):
    """LLM response describing a single storage key."""

    description: str
    set_by: str = pydantic.Field(alias="setBy", serialization_alias="setBy")
    purpose: str
    risk_level: str = pydantic.Field(alias="riskLevel", serialization_alias="riskLevel")
    privacy_note: str = pydantic.Field(alias="privacyNote", serialization_alias="privacyNote")

    # Optional vendor enrichment (populated from cross-reference data).
    vendor_category: str | None = pydantic.Field(
        default=None,
        alias="vendorCategory",
        serialization_alias="vendorCategory",
    )
    vendor_url: str | None = pydantic.Field(
        default=None,
        alias="vendorUrl",
        serialization_alias="vendorUrl",
    )
    vendor_concerns: list[str] | None = pydantic.Field(
        default=None,
        alias="vendorConcerns",
        serialization_alias="vendorConcerns",
    )
    vendor_gvl_ids: list[int] | None = pydantic.Field(
        default=None,
        alias="vendorGvlIds",
        serialization_alias="vendorGvlIds",
    )
    vendor_atp_ids: list[int] | None = pydantic.Field(
        default=None,
        alias="vendorAtpIds",
        serialization_alias="vendorAtpIds",
    )

    model_config = pydantic.ConfigDict(populate_by_name=True)


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
        log.debug("Explaining storage key via LLM", {"key": key, "type": storage_type})

        try:
            response = await self._complete(user_message)
            parsed = self._parse_response(response, StorageInfoResult)
            if parsed:
                return parsed

            # Fallback: manual JSON parse from response text
            raw = json_parsing.load_json_from_text(response.text)
            if isinstance(raw, dict):
                try:
                    return StorageInfoResult.model_validate(raw)
                except Exception:
                    pass

            log.warn("Failed to parse storage info response", {"key": key})
            return None
        except Exception as exc:
            log.warn(
                f"Storage info LLM call failed: {exc}",
                {"key": key, "type": storage_type},
            )
            return None
