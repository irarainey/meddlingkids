"""Tests for src.pipeline.analysis_pipeline — pure render functions."""

from __future__ import annotations

from src.models import analysis
from src.pipeline.analysis_pipeline import (
    _render_header,
    _render_pre_consent_stats,
    _render_score_breakdown,
    _render_summary_findings,
)


class TestRenderHeader:
    """Tests for _render_header()."""

    def test_contains_url(self) -> None:
        lines = _render_header("https://example.com", 75, "High risk")
        text = "\n".join(lines)
        assert "example.com" in text
        assert "75/100" in text
        assert "High risk" in text

    def test_has_timestamp(self) -> None:
        lines = _render_header("https://test.com", 50, "Moderate")
        text = "\n".join(lines)
        assert "UTC" in text

    def test_has_separator(self) -> None:
        lines = _render_header("https://test.com", 50, "Moderate")
        assert "=" * 72 in lines[0]


class TestRenderScoreBreakdown:
    """Tests for _render_score_breakdown()."""

    def test_none_returns_empty(self) -> None:
        assert _render_score_breakdown(None) == []

    def test_empty_categories_returns_empty(self) -> None:
        sb = analysis.ScoreBreakdown(total_score=0)
        assert _render_score_breakdown(sb) == []

    def test_with_categories(self) -> None:
        sb = analysis.ScoreBreakdown(
            total_score=65,
            categories={
                "cookies": analysis.CategoryScore(
                    points=10,
                    max_points=22,
                    issues=["20 cookies set"],
                ),
            },
            factors=["Many cookies"],
        )
        lines = _render_score_breakdown(sb)
        text = "\n".join(lines)
        assert "SCORE BREAKDOWN" in text
        assert "cookies: 10/22" in text
        assert "20 cookies set" in text
        assert "Many cookies" in text


class TestRenderPreConsentStats:
    """Tests for _render_pre_consent_stats()."""

    def test_none_returns_empty(self) -> None:
        assert _render_pre_consent_stats(None) == []

    def test_with_stats(self) -> None:
        stats = analysis.PreConsentStats(
            total_cookies=10,
            tracking_cookies=3,
            total_scripts=20,
            tracking_scripts=5,
            total_requests=100,
            tracker_requests=15,
            total_local_storage=3,
            total_session_storage=1,
        )
        lines = _render_pre_consent_stats(stats)
        text = "\n".join(lines)
        assert "PRE-CONSENT" in text
        assert "10" in text
        assert "tracking: 3" in text


class TestRenderSummaryFindings:
    """Tests for _render_summary_findings()."""

    def test_empty_returns_empty(self) -> None:
        assert _render_summary_findings([]) == []

    def test_with_findings(self) -> None:
        findings = [
            analysis.SummaryFinding(type="critical", text="No consent dialog"),
            analysis.SummaryFinding(type="high", text="Many trackers"),
            analysis.SummaryFinding(type="positive", text="HTTPS everywhere"),
        ]
        lines = _render_summary_findings(findings)
        text = "\n".join(lines)
        assert "SUMMARY" in text
        assert "[CRITICAL]" in text
        assert "No consent dialog" in text
        assert "[POSITIVE]" in text
