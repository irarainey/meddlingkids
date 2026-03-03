"""Shared risk-scoring helpers used by multiple agents."""

from __future__ import annotations

# ── Risk-score thresholds ───────────────────────────────────────

CRITICAL_THRESHOLD = 80
HIGH_THRESHOLD = 60
MODERATE_THRESHOLD = 40
LOW_THRESHOLD = 20


def risk_label(score: int) -> str:
    """Map a 0-100 score to a human risk label."""
    if score >= CRITICAL_THRESHOLD:
        return "Critical Risk"
    if score >= HIGH_THRESHOLD:
        return "High Risk"
    if score >= MODERATE_THRESHOLD:
        return "Moderate Risk"
    if score >= LOW_THRESHOLD:
        return "Low Risk"
    return "Very Low Risk"
