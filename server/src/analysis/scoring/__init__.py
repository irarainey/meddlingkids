"""Privacy scoring package.

Decomposes the privacy score calculation into focused modules,
one per scoring category.  The public API is
:func:`calculate_privacy_score`.
"""

from __future__ import annotations

from src.analysis.scoring.calculator import calculate_privacy_score

__all__ = ["calculate_privacy_score"]
