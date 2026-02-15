"""Tests for the domain knowledge cache.

Covers name normalisation, fuzzy matching, merge/prune
behaviour, context hint formatting, and file I/O via
``tmp_path``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.analysis import domain_cache
from src.models import report


# ── Name normalisation ──────────────────────────────────────────


class TestNormalizeName:
    """Tests for _normalize_name."""

    def test_strips_parenthetical(self) -> None:
        assert domain_cache._normalize_name("Comscore (Scorecard Research)") == "comscore"

    def test_strips_filler_words(self) -> None:
        assert domain_cache._normalize_name("Google Services") == "google"

    def test_sorts_tokens(self) -> None:
        result = domain_cache._normalize_name("Zeta Alpha")
        assert result == "alpha zeta"

    def test_lowered(self) -> None:
        assert domain_cache._normalize_name("FACEBOOK") == "facebook"

    def test_collapses_whitespace(self) -> None:
        assert domain_cache._normalize_name("a  -  b") == "a b"


# ── Name matching ───────────────────────────────────────────────


class TestNamesMatch:
    """Tests for _names_match."""

    def test_identical(self) -> None:
        assert domain_cache._names_match("comscore", "comscore")

    def test_subset(self) -> None:
        assert domain_cache._names_match("comscore", "comscore research")

    def test_disjoint(self) -> None:
        assert not domain_cache._names_match("google", "facebook")

    def test_paren_cross_match(self) -> None:
        assert domain_cache._names_match(
            "comscore",
            "research scorecard",
            raw_a="Comscore",
            raw_b="Scorecard Research (Comscore)",
        )


# ── Prune stale ─────────────────────────────────────────────────


class TestPruneStale:
    """Tests for _prune_stale."""

    def test_keeps_recent(self) -> None:
        items = [
            domain_cache.CachedTracker(name="A", category="analytics", purpose="p", last_seen_scan=10),
        ]
        result = domain_cache._prune_stale(items, current_scan=11)
        assert len(result) == 1

    def test_prunes_old(self) -> None:
        items = [
            domain_cache.CachedTracker(name="A", category="analytics", purpose="p", last_seen_scan=5),
        ]
        result = domain_cache._prune_stale(items, current_scan=10)
        assert len(result) == 0

    def test_boundary(self) -> None:
        items = [
            domain_cache.CachedTracker(name="A", category="analytics", purpose="p", last_seen_scan=7),
        ]
        # _STALE_SCAN_THRESHOLD is 3 → age 3 is kept, age 4 is pruned
        kept = domain_cache._prune_stale(items, current_scan=10)
        assert len(kept) == 1
        pruned = domain_cache._prune_stale(items, current_scan=11)
        assert len(pruned) == 0


# ── Merge helpers ───────────────────────────────────────────────


class TestMergeByKey:
    """Tests for _merge_by_key."""

    def test_new_replaces_old(self) -> None:
        old = [domain_cache.CachedCookieGroup(category="Analytics", cookies=["_ga"], concern_level="high", last_seen_scan=1)]
        new = [domain_cache.CachedCookieGroup(category="analytics", cookies=["_ga", "_gid"], concern_level="medium", last_seen_scan=2)]
        result = domain_cache._merge_by_key(old, new, key=lambda g: g.category.lower())
        assert len(result) == 1
        assert result[0].cookies == ["_ga", "_gid"]

    def test_carries_forward_old(self) -> None:
        old = [
            domain_cache.CachedCookieGroup(category="targeting", cookies=["IDE"], concern_level="high", last_seen_scan=1),
        ]
        new = [
            domain_cache.CachedCookieGroup(category="analytics", cookies=["_ga"], concern_level="low", last_seen_scan=2),
        ]
        result = domain_cache._merge_by_key(old, new, key=lambda g: g.category.lower())
        assert len(result) == 2
        categories = {g.category for g in result}
        assert "targeting" in categories
        assert "analytics" in categories


class TestMergeByName:
    """Tests for _merge_by_name with fuzzy matching."""

    def test_exact_dedup(self) -> None:
        old = [domain_cache.CachedTracker(name="Google", category="analytics", purpose="p", last_seen_scan=1)]
        new = [domain_cache.CachedTracker(name="Google", category="analytics", purpose="p2", last_seen_scan=2)]
        result = domain_cache._merge_by_name(old, new, name_attr="name")
        assert len(result) == 1
        assert result[0].purpose == "p2"

    def test_fuzzy_dedup(self) -> None:
        old = [domain_cache.CachedTracker(name="Comscore", category="analytics", purpose="p", last_seen_scan=1)]
        new = [domain_cache.CachedTracker(name="Scorecard Research (Comscore)", category="analytics", purpose="p2", last_seen_scan=2)]
        result = domain_cache._merge_by_name(old, new, name_attr="name")
        assert len(result) == 1

    def test_distinct_items_kept(self) -> None:
        old = [domain_cache.CachedTracker(name="Facebook", category="social", purpose="p", last_seen_scan=1)]
        new = [domain_cache.CachedTracker(name="Google", category="analytics", purpose="p2", last_seen_scan=2)]
        result = domain_cache._merge_by_name(old, new, name_attr="name")
        assert len(result) == 2


# ── Build context hint ──────────────────────────────────────────


class TestBuildContextHint:
    """Tests for build_context_hint."""

    def test_empty_knowledge(self) -> None:
        knowledge = domain_cache.DomainKnowledge(domain="example.com")
        hint = domain_cache.build_context_hint(knowledge)
        assert "Previous Analysis Context" in hint

    def test_includes_trackers(self) -> None:
        knowledge = domain_cache.DomainKnowledge(
            domain="example.com",
            trackers=[domain_cache.CachedTracker(name="GA", category="analytics", purpose="measurement")],
        )
        hint = domain_cache.build_context_hint(knowledge)
        assert "GA" in hint
        assert "analytics" in hint

    def test_includes_vendors(self) -> None:
        knowledge = domain_cache.DomainKnowledge(
            domain="example.com",
            vendors=[domain_cache.CachedVendor(name="Google", role="Ad network")],
        )
        hint = domain_cache.build_context_hint(knowledge)
        assert "Google" in hint
        assert "Ad network" in hint


# ── Load / Save round-trip ──────────────────────────────────────


class TestDomainCacheIO:
    """Tests for load/save with ``tmp_path``."""

    def test_load_nonexistent(self, tmp_path) -> None:
        with patch.object(domain_cache, "_CACHE_DIR", tmp_path):
            result = domain_cache.load("nonexistent.com")
            assert result is None

    def test_save_and_load_roundtrip(self, tmp_path) -> None:
        with patch.object(domain_cache, "_CACHE_DIR", tmp_path):
            sr = report.StructuredReport(
                tracking_technologies=report.TrackingTechnologiesSection(
                    analytics=[
                        report.TrackerEntry(name="GA4", domains=["google-analytics.com"], purpose="Analytics"),
                    ],
                ),
                cookie_analysis=report.CookieAnalysisSection(
                    total=5,
                    groups=[
                        report.CookieGroup(category="Analytics", cookies=["_ga", "_gid"], concern_level="medium"),
                    ],
                ),
                key_vendors=report.VendorSection(
                    vendors=[
                        report.VendorEntry(name="Google", role="Analytics provider", privacy_impact="Medium"),
                    ],
                ),
                data_collection=report.DataCollectionSection(
                    items=[
                        report.DataCollectionItem(category="Browsing", details=["pages"], risk="low"),
                    ],
                ),
            )
            domain_cache.save_from_report("example.com", sr)

            loaded = domain_cache.load("example.com")
            assert loaded is not None
            assert loaded.domain == "example.com"
            assert loaded.scan_count == 1
            assert len(loaded.trackers) == 1
            assert loaded.trackers[0].name == "GA4"

    def test_domain_path_strips_www(self) -> None:
        path_a = domain_cache._domain_path("www.example.com")
        path_b = domain_cache._domain_path("example.com")
        assert path_a == path_b

    def test_load_corrupt_file(self, tmp_path) -> None:
        with patch.object(domain_cache, "_CACHE_DIR", tmp_path):
            path = tmp_path / "bad.com.json"
            path.write_text("{invalid json", encoding="utf-8")
            # Should not raise; returns None after removing file
            result = domain_cache.load("bad.com")
            assert result is None
