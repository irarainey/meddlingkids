"""Storage key information lookup service.

Provides storage key explanations by checking known databases first
(tracking storage patterns) and falling back to LLM for unrecognised
keys.
"""

from __future__ import annotations

from src.agents import storage_info_agent
from src.data import loader
from src.models import item_info
from src.utils import logger

log = logger.create_logger("StorageLookup")


def _attach_vendor_metadata(result: storage_info_agent.StorageInfoResult) -> storage_info_agent.StorageInfoResult:
    """Enrich a storage result with vendor cross-reference data."""
    return item_info.attach_vendor_metadata(result, loader.get_tracking_storage_vendor_index())


def _check_tracking_storage_pattern(key: str) -> storage_info_agent.StorageInfoResult | None:
    """Check if a storage key matches known tracking storage patterns.

    Returns a pre-built result if it matches a well-known key.
    """
    risk_map = loader.get_tracking_storage_risk_map()
    privacy_map = loader.get_tracking_storage_privacy_map()

    for pattern, description, set_by, purpose in loader.get_tracking_storage_patterns():
        if pattern.search(key):
            return storage_info_agent.StorageInfoResult(
                description=description,
                setBy=set_by,
                purpose=purpose,
                riskLevel=risk_map.get(purpose, "medium"),
                privacyNote=privacy_map.get(purpose, ""),
            )

    return None


async def get_storage_info(
    key: str,
    storage_type: str,
    value: str,
    agent: storage_info_agent.StorageInfoAgent,
) -> storage_info_agent.StorageInfoResult:
    """Look up information about a storage key.

    Checks known databases first, then falls back to LLM.

    Args:
        key: Storage key name.
        storage_type: Type of storage ("localStorage" or "sessionStorage").
        value: Storage value.
        agent: The LLM agent instance for fallback lookups.

    Returns:
        Structured storage key information.
    """
    # 1. Check tracking storage patterns
    result = _check_tracking_storage_pattern(key)
    if result:
        log.debug("Storage key matched tracking pattern", {"key": key})
        return _attach_vendor_metadata(result)

    # 2. Fall back to LLM
    log.info("Storage key not in databases, querying LLM", {"key": key, "type": storage_type})
    llm_result = await agent.explain(key, storage_type, value)
    if llm_result:
        return llm_result

    # 3. Last resort — minimal generic info
    return storage_info_agent.StorageInfoResult(
        description="Purpose could not be determined for this storage key.",
        setBy="Unknown",
        purpose="unknown",
        riskLevel="low",
        privacyNote="",
    )
