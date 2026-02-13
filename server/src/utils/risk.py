"""Shared risk-scoring helpers used by multiple agents."""

from __future__ import annotations


def risk_label(score: int) -> str:
    """Map a 0-100 score to a human risk label."""
    if score >= 80:
        return "Critical Risk"
    if score >= 60:
        return "High Risk"
    if score >= 40:
        return "Moderate Risk"
    if score >= 20:
        return "Low Risk"
    return "Very Low Risk"
