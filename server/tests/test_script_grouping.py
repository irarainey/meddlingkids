"""Tests for src.analysis.script_grouping — script collapse logic."""

from __future__ import annotations

import pytest

from src.analysis.script_grouping import (
    GROUPABLE_PATTERNS,
    MIN_GROUP_SIZE,
    GroupedScriptsResult,
    GroupPattern,
    group_similar_scripts,
)
from src.models.tracking_data import TrackedScript

# ── helpers ─────────────────────────────────────────────────────


def _script(url: str, domain: str = "example.com") -> TrackedScript:
    return TrackedScript(url=url, domain=domain)


# ── GroupPattern catalogue ──────────────────────────────────────


class TestGroupablePatterns:
    """Ensure every catalogue pattern matches at least one expected URL."""

    def test_all_entries_are_group_patterns(self) -> None:
        for gp in GROUPABLE_PATTERNS:
            assert isinstance(gp, GroupPattern)

    @pytest.mark.parametrize(
        ("pattern_id", "url"),
        [
            ("app-chunks", "https://example.com/chunk-a3bf21c9.js"),
            ("app-chunks", "https://example.com/_next/static/chunks/main.js"),
            ("vendor-bundles", "https://example.com/vendor-ab12cd.js"),
            ("vendor-bundles", "https://example.com/node_modules/react.js"),
            ("webpack-runtime", "https://example.com/webpack-runtime-abc123.js"),
            ("lazy-modules", "https://example.com/lazy-ab12cd.js"),
            ("css-chunks", "https://example.com/styles-ab12cd.js"),
            ("polyfills", "https://example.com/polyfills-ab12cd.js"),
            ("polyfills", "https://example.com/core-js/something.js"),
            ("static-assets", "https://example.com/static/js/main.abcdef12.js"),
        ],
    )
    def test_pattern_matches_url(self, pattern_id: str, url: str) -> None:
        gp = next(p for p in GROUPABLE_PATTERNS if p.id == pattern_id)
        assert gp.pattern.search(url), f"{pattern_id} should match {url}"


# ── group_similar_scripts ──────────────────────────────────────


class TestGroupSimilarScripts:
    def test_empty_input(self) -> None:
        result = group_similar_scripts([])
        assert isinstance(result, GroupedScriptsResult)
        assert result.individual_scripts == []
        assert result.groups == []
        assert result.all_scripts == []

    def test_single_ungroupable_script(self) -> None:
        s = _script("https://example.com/custom.js")
        result = group_similar_scripts([s])
        assert len(result.individual_scripts) == 1
        assert result.groups == []

    def test_below_min_group_size(self) -> None:
        """A single chunk script should NOT be grouped when < MIN_GROUP_SIZE."""
        scripts = [_script("https://example.com/chunk-abc123.js")]
        result = group_similar_scripts(scripts)
        # Falls below threshold → stays individual
        assert len(result.individual_scripts) == 1
        assert result.groups == []

    def test_meets_min_group_size(self) -> None:
        """Two chunk scripts from the same domain collapse into a group."""
        scripts = [
            _script("https://example.com/chunk-abc123.js"),
            _script("https://example.com/chunk-def456.js"),
        ]
        result = group_similar_scripts(scripts)
        assert len(result.groups) == 1
        assert result.groups[0].count == 2
        assert result.groups[0].name == "Application code chunks"
        assert result.groups[0].domain == "example.com"
        # Grouped scripts are marked
        grouped = [s for s in result.all_scripts if s.is_grouped]
        assert len(grouped) == 2

    def test_different_domains_stay_separate(self) -> None:
        """Same pattern from different domains → separate groups."""
        scripts = [
            _script("https://a.com/chunk-abc12345.js", domain="a.com"),
            _script("https://a.com/chunk-def45678.js", domain="a.com"),
            _script("https://b.com/chunk-aaa11111.js", domain="b.com"),
            _script("https://b.com/chunk-bbb22222.js", domain="b.com"),
        ]
        result = group_similar_scripts(scripts)
        assert len(result.groups) == 2

    def test_mixed_groupable_and_individual(self) -> None:
        scripts = [
            _script("https://example.com/chunk-abc123.js"),
            _script("https://example.com/chunk-def456.js"),
            _script("https://example.com/custom-app.js"),
        ]
        result = group_similar_scripts(scripts)
        assert len(result.groups) == 1
        assert len(result.individual_scripts) == 1

    def test_example_urls_limited_to_three(self) -> None:
        scripts = [_script(f"https://example.com/chunk-{i:06x}.js") for i in range(5)]
        result = group_similar_scripts(scripts)
        assert len(result.groups) == 1
        assert len(result.groups[0].example_urls) <= 3

    def test_min_group_size_value(self) -> None:
        assert MIN_GROUP_SIZE == 2
