"""Backward-compatible re-export.

The scoring logic now lives in :mod:`src.analysis.scoring`.
This module preserves the old import path.
"""

from src.analysis.scoring import calculate_privacy_score

__all__ = ["calculate_privacy_score"]
