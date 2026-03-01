"""Tests for src.utils.risk — risk level label mapping."""

from __future__ import annotations

import pytest

from src.utils.risk import risk_label


class TestRiskLabel:
    """Tests for risk_label()."""

    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (100, "Critical Risk"),
            (80, "Critical Risk"),
            (79, "High Risk"),
            (60, "High Risk"),
            (59, "Moderate Risk"),
            (40, "Moderate Risk"),
            (39, "Low Risk"),
            (20, "Low Risk"),
            (19, "Very Low Risk"),
            (0, "Very Low Risk"),
        ],
    )
    def test_risk_label_boundaries(self, score: int, expected: str) -> None:
        assert risk_label(score) == expected
