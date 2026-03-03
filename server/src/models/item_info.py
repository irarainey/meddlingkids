"""Shared Pydantic model for cookie and storage info results.

Both ``CookieInfoAgent`` and ``StorageInfoAgent`` return
structurally identical results: five core description fields
plus five optional vendor-enrichment fields.  This module
defines that shared schema once and provides a generic
vendor-metadata attachment helper.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pydantic


class ItemInfoResult(pydantic.BaseModel):
    """LLM response describing a single cookie or storage key.

    Subclassed (without additional fields) by the cookie and
    storage info agents so each retains its own name for logs
    and error messages.
    """

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


# ── Vendor enrichment helper ────────────────────────────────────

_VENDOR_FIELDS = ("category", "url", "concerns", "gvl_ids", "atp_ids")


def attach_vendor_metadata[T: ItemInfoResult](
    result: T,
    vendor_index: Mapping[str, dict[str, Any]],
) -> T:
    """Enrich *result* with vendor cross-reference data.

    Looks up ``result.set_by`` in *vendor_index* and populates
    the optional ``vendor_*`` fields when a match is found.

    This is a generic helper shared by the cookie and storage
    lookup modules — each passes its own index.

    Args:
        result: An ``ItemInfoResult`` (or subclass) to enrich.
        vendor_index: Mapping from vendor name to metadata dict.

    Returns:
        The same *result* instance, mutated in-place.
    """
    vendor = vendor_index.get(result.set_by)
    if not vendor:
        return result
    for field in _VENDOR_FIELDS:
        setattr(result, f"vendor_{field}", vendor.get(field))
    return result
