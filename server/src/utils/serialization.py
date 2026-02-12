"""Shared serialization helpers for camelCase conversion.

Provides a single ``snake_to_camel`` implementation used by
Pydantic model configs and SSE event builders.
"""

from __future__ import annotations


def snake_to_camel(name: str) -> str:
    """Convert a snake_case string to camelCase.

    Args:
        name: A snake_case identifier such as
            ``"my_field_name"``.

    Returns:
        The camelCase equivalent, e.g. ``"myFieldName"``.
    """
    parts = name.split("_")
    return parts[0] + "".join(w.capitalize() for w in parts[1:])
