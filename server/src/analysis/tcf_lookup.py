"""TCF purpose matching service.

Maps purpose strings extracted from consent dialogs to the
IAB Transparency & Consent Framework v2.2 purpose taxonomy.
Matching is purely deterministic — no LLM calls.
"""

from __future__ import annotations

import functools
import re
from typing import Any, Literal

import pydantic

from src.data import loader

TcfCategory = Literal["purpose", "special-purpose", "feature", "special-feature"]


class TcfPurposeMatch(pydantic.BaseModel):
    """A matched TCF purpose with full metadata."""

    id: int
    name: str
    description: str
    risk_level: str
    lawful_bases: list[str]
    notes: str
    category: TcfCategory

    model_config = pydantic.ConfigDict(
        alias_generator=lambda s: re.sub(r"_([a-z])", lambda m: m.group(1).upper(), s),
        populate_by_name=True,
    )


class TcfLookupResult(pydantic.BaseModel):
    """Result of mapping purpose strings to TCF purposes."""

    matched: list[TcfPurposeMatch]
    unmatched: list[str]

    model_config = pydantic.ConfigDict(
        alias_generator=lambda s: re.sub(r"_([a-z])", lambda m: m.group(1).upper(), s),
        populate_by_name=True,
    )


# Characters to strip for normalised comparison.
_STRIP_RE = re.compile(r"[^a-z0-9 ]")


def _normalise(text: str) -> str:
    """Lower-case, strip non-alphanumeric characters, collapse whitespace."""
    return _STRIP_RE.sub("", text.lower()).strip()


def _build_index() -> list[tuple[str, TcfPurposeMatch]]:
    """Build a searchable index of all TCF items.

    Returns a list of ``(normalised_name, TcfPurposeMatch)`` tuples
    covering purposes, special purposes, features, and special features.
    """
    data = loader.get_tcf_purposes()
    index: list[tuple[str, TcfPurposeMatch]] = []

    section_map: list[tuple[str, TcfCategory]] = [
        ("purposes", "purpose"),
        ("special_purposes", "special-purpose"),
        ("features", "feature"),
        ("special_features", "special-feature"),
    ]

    for section_key, category in section_map:
        section: dict[str, Any] = data.get(section_key, {})
        for entry in section.values():
            match = TcfPurposeMatch(
                id=entry["id"],
                name=entry["name"],
                description=entry["description"],
                risk_level=entry.get("risk_level", "medium"),
                lawful_bases=entry.get("lawful_bases", []),
                notes=entry.get("notes", ""),
                category=category,
            )
            index.append((_normalise(entry["name"]), match))

    return index


@functools.cache
def _get_index() -> tuple[tuple[str, TcfPurposeMatch], ...]:
    """Return the cached TCF index, building it on first access."""
    return tuple(_build_index())


def _match_purpose(purpose: str) -> TcfPurposeMatch | None:
    """Attempt to match a single purpose string to a TCF item.

    Tries exact normalised match first, then substring containment
    in both directions (purpose contains TCF name, or TCF name
    contains purpose) for resilience to minor wording differences.
    """
    norm = _normalise(purpose)
    if not norm:
        return None

    index = _get_index()

    # Pass 1: exact normalised match.
    for tcf_norm, match in index:
        if norm == tcf_norm:
            return match

    # Pass 2: the purpose string contains the full TCF name.
    for tcf_norm, match in index:
        if tcf_norm in norm:
            return match

    # Pass 3: the TCF name contains the full purpose string.
    # Only when the purpose string is long enough to be meaningful
    # (avoids false positives from very short strings).
    if len(norm) >= 12:
        for tcf_norm, match in index:
            if norm in tcf_norm:
                return match

    return None


def lookup_purposes(purposes: list[str]) -> TcfLookupResult:
    """Map a list of purpose strings to TCF purposes.

    Returns:
        A ``TcfLookupResult`` containing matched TCF purposes
        (deduplicated by ID + category) and any unmatched strings.
    """
    matched: list[TcfPurposeMatch] = []
    unmatched: list[str] = []
    seen: set[tuple[int, str]] = set()

    for purpose in purposes:
        result = _match_purpose(purpose)
        if result is not None:
            key = (result.id, result.category)
            if key not in seen:
                seen.add(key)
                matched.append(result)
        else:
            unmatched.append(purpose)

    # Sort by category priority then ID.
    category_order: dict[str, int] = {
        "purpose": 0,
        "special-purpose": 1,
        "feature": 2,
        "special-feature": 3,
    }
    matched.sort(key=lambda m: (category_order.get(m.category, 99), m.id))

    return TcfLookupResult(matched=matched, unmatched=unmatched)
