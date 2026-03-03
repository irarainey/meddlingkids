"""Shared table-driven scoring helper.

Provides a small utility that replaces repetitive if/elif
threshold chains with declarative tier tables.
"""

from __future__ import annotations

from collections.abc import Sequence

# (threshold, points, issue_template_or_None)
# Tiers must be listed in descending threshold order.
# *issue_template* may contain ``{n}`` which is replaced
# with the evaluated count.  ``None`` means no issue text.
Tier = tuple[int, int, str | None]


def score_by_tiers(
    count: int,
    tiers: Sequence[Tier],
) -> tuple[int, str | None]:
    """Score *count* against descending threshold tiers.

    The first tier whose threshold is strictly less than
    *count* wins.

    Args:
        count: The value to evaluate.
        tiers: ``(threshold, points, issue_template)`` tuples
            in **descending** threshold order.

    Returns:
        ``(points, issue_or_None)`` for the first matching
        tier, or ``(0, None)`` when no tier matches.
    """
    for threshold, points, template in tiers:
        if count > threshold:
            issue = template.format(n=count) if template else None
            return points, issue
    return 0, None
