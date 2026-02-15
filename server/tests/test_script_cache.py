"""Tests for the script analysis cache.

Covers hashing, lookup with hash validation, save/load
round-trips, and stale entry invalidation.
"""

from __future__ import annotations

from unittest.mock import patch

from src.analysis import script_cache


# ── Hashing ─────────────────────────────────────────────────────


class TestComputeHash:
    """Tests for compute_hash."""

    def test_deterministic(self) -> None:
        assert script_cache.compute_hash("hello") == script_cache.compute_hash("hello")

    def test_different_content(self) -> None:
        assert script_cache.compute_hash("a") != script_cache.compute_hash("b")

    def test_returns_hex_string(self) -> None:
        h = script_cache.compute_hash("test")
        assert isinstance(h, str)
        assert len(h) == 32  # MD5 hex digest


# ── Lookup ──────────────────────────────────────────────────────


class TestLookup:
    """Tests for cache lookup with hash validation."""

    def test_cache_hit(self) -> None:
        entry = script_cache.ScriptCacheEntry(
            domain="example.com",
            scripts=[
                script_cache.CachedScript(url="https://example.com/a.js", content_hash="abc", description="Analytics"),
            ],
        )
        result = script_cache.lookup(entry, "https://example.com/a.js", "abc")
        assert result == "Analytics"

    def test_cache_miss_url_not_found(self) -> None:
        entry = script_cache.ScriptCacheEntry(domain="example.com", scripts=[])
        result = script_cache.lookup(entry, "https://example.com/a.js", "abc")
        assert result is None

    def test_cache_miss_hash_mismatch(self) -> None:
        entry = script_cache.ScriptCacheEntry(
            domain="example.com",
            scripts=[
                script_cache.CachedScript(url="https://example.com/a.js", content_hash="old", description="Old desc"),
            ],
        )
        result = script_cache.lookup(entry, "https://example.com/a.js", "new")
        assert result is None
        # Stale entry should be removed
        assert len(entry.scripts) == 0


# ── Save / Load round-trip ──────────────────────────────────────


class TestScriptCacheIO:
    """Tests for save and load operations."""

    def test_save_and_load(self, tmp_path) -> None:
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            analyzed = [
                script_cache.CachedScript(url="https://example.com/a.js", content_hash="h1", description="Tracker"),
                script_cache.CachedScript(url="https://example.com/b.js", content_hash="h2", description="Analytics"),
            ]
            script_cache.save("example.com", analyzed)

            loaded = script_cache.load("example.com")
            assert loaded is not None
            assert len(loaded.scripts) == 2
            assert loaded.scripts[0].description == "Tracker"

    def test_load_nonexistent(self, tmp_path) -> None:
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            result = script_cache.load("nonexistent.com")
            assert result is None

    def test_save_merges_with_existing(self, tmp_path) -> None:
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            existing = script_cache.ScriptCacheEntry(
                domain="example.com",
                scripts=[
                    script_cache.CachedScript(url="https://example.com/old.js", content_hash="h0", description="Old"),
                ],
            )
            # Save existing first
            script_cache.save("example.com", existing.scripts)

            # Now save new entries, passing existing to carry forward
            loaded_existing = script_cache.load("example.com")
            new_scripts = [
                script_cache.CachedScript(url="https://example.com/new.js", content_hash="h1", description="New"),
            ]
            script_cache.save("example.com", new_scripts, existing=loaded_existing)

            final = script_cache.load("example.com")
            assert final is not None
            assert len(final.scripts) == 2
            urls = {s.url for s in final.scripts}
            assert "https://example.com/old.js" in urls
            assert "https://example.com/new.js" in urls

    def test_domain_path_strips_www(self) -> None:
        path_a = script_cache._domain_path("www.example.com")
        path_b = script_cache._domain_path("example.com")
        assert path_a == path_b

    def test_load_corrupt_file(self, tmp_path) -> None:
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            path = tmp_path / "bad.com.json"
            path.write_text("{broken", encoding="utf-8")
            result = script_cache.load("bad.com")
            assert result is None
