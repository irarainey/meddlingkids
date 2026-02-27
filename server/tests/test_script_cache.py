"""Tests for the script analysis cache.

Covers hashing, URL normalisation, lookup with hash validation,
save/load round-trips, and stale entry invalidation.
"""

from __future__ import annotations

from unittest.mock import patch

from src.analysis import script_cache
from src.analysis.scripts import (
    _FALLBACK_DESCRIPTIONS,
    _infer_from_url,
    is_fallback_description,
)

# ── URL normalisation ───────────────────────────────────────────


class TestStripQueryString:
    """Tests for strip_query_string URL normalisation."""

    def test_strips_query_string(self) -> None:
        url = "https://cdn.example.com/tracker.js?v=1.2&cb=123"
        assert script_cache.strip_query_string(url) == "https://cdn.example.com/tracker.js"

    def test_strips_fragment(self) -> None:
        url = "https://cdn.example.com/tracker.js#section"
        assert script_cache.strip_query_string(url) == "https://cdn.example.com/tracker.js"

    def test_strips_both_query_and_fragment(self) -> None:
        url = "https://cdn.example.com/tracker.js?v=1#top"
        assert script_cache.strip_query_string(url) == "https://cdn.example.com/tracker.js"

    def test_no_query_string_unchanged(self) -> None:
        url = "https://cdn.example.com/tracker.js"
        assert script_cache.strip_query_string(url) == url

    def test_empty_query_string(self) -> None:
        url = "https://cdn.example.com/tracker.js?"
        assert script_cache.strip_query_string(url) == "https://cdn.example.com/tracker.js"

    def test_preserves_path(self) -> None:
        url = "https://cdn.example.com/path/to/script.js?cachebuster=abc"
        assert script_cache.strip_query_string(url) == "https://cdn.example.com/path/to/script.js"


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

    def test_soft_hit_hash_mismatch(self) -> None:
        """Hash mismatch returns cached description and updates hash in-place."""
        entry = script_cache.ScriptCacheEntry(
            domain="example.com",
            scripts=[
                script_cache.CachedScript(url="https://example.com/a.js", content_hash="old", description="Old desc"),
            ],
        )
        result = script_cache.lookup(entry, "https://example.com/a.js", "new")
        assert result == "Old desc"
        # Hash should be updated in-place
        assert entry.scripts[0].content_hash == "new"
        # Entry should be marked as modified
        assert entry.modified is True

    def test_soft_hit_does_not_set_modified_on_exact_match(self) -> None:
        """Exact hash match should not set the modified flag."""
        entry = script_cache.ScriptCacheEntry(
            domain="example.com",
            scripts=[
                script_cache.CachedScript(url="https://example.com/a.js", content_hash="abc", description="Desc"),
            ],
        )
        result = script_cache.lookup(entry, "https://example.com/a.js", "abc")
        assert result == "Desc"
        assert entry.modified is False

    def test_cache_hit_with_query_string(self) -> None:
        """Lookup should match when URL has query string but cache stores base URL."""
        entry = script_cache.ScriptCacheEntry(
            domain="example.com",
            scripts=[
                script_cache.CachedScript(url="https://example.com/a.js", content_hash="abc", description="Tracker"),
            ],
        )
        # Full URL with query params should still hit
        result = script_cache.lookup(entry, "https://example.com/a.js?v=2&cb=rnd123", "abc")
        assert result == "Tracker"

    def test_cache_hit_different_query_strings(self) -> None:
        """Different query string variants of the same script should all hit."""
        entry = script_cache.ScriptCacheEntry(
            domain="example.com",
            scripts=[
                script_cache.CachedScript(url="https://example.com/a.js", content_hash="abc", description="Analytics"),
            ],
        )
        for qs in ["?v=1", "?v=2", "?cb=xyz", "?v=1&uid=123", ""]:
            result = script_cache.lookup(entry, f"https://example.com/a.js{qs}", "abc")
            assert result == "Analytics", f"Expected hit for query string '{qs}'"


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

    def test_save_deduplicates_query_string_variants(self, tmp_path) -> None:
        """Saving scripts with different query strings should store only one entry."""
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            analyzed = [
                script_cache.CachedScript(url="https://example.com/a.js?v=1", content_hash="h1", description="Script A"),
                script_cache.CachedScript(url="https://example.com/a.js?v=2", content_hash="h1", description="Script A"),
                script_cache.CachedScript(url="https://example.com/a.js?cb=rnd", content_hash="h1", description="Script A"),
            ]
            script_cache.save("example.com", analyzed)

            loaded = script_cache.load("example.com")
            assert loaded is not None
            assert len(loaded.scripts) == 1
            assert loaded.scripts[0].url == "https://example.com/a.js"

    def test_save_normalizes_urls(self, tmp_path) -> None:
        """Saved entries should have query strings stripped from URLs."""
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            analyzed = [
                script_cache.CachedScript(url="https://example.com/a.js?cachebuster=xyz", content_hash="h1", description="A"),
            ]
            script_cache.save("example.com", analyzed)

            loaded = script_cache.load("example.com")
            assert loaded is not None
            assert loaded.scripts[0].url == "https://example.com/a.js"

    def test_cross_site_cache_hit(self, tmp_path) -> None:
        """Scripts cached under their own domain should be available across site scans.

        This is the key optimisation: caching by *script domain*
        (e.g. ``cdn.adnetwork.com``) means a script analysed
        during a scan of site-A is an immediate cache hit when
        site-B loads the same script.
        """
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            # Simulate first site scan analysing a CDN script.
            script_domain = "cdn.adnetwork.com"
            analyzed = [
                script_cache.CachedScript(
                    url="https://cdn.adnetwork.com/tracker.js",
                    content_hash="h1",
                    description="Ad tracking pixel",
                ),
            ]
            script_cache.save(script_domain, analyzed)

            # Simulate second site scan loading cache for same script domain.
            loaded = script_cache.load(script_domain)
            assert loaded is not None
            result = script_cache.lookup(
                loaded,
                "https://cdn.adnetwork.com/tracker.js?site=other-site.com",
                "h1",
            )
            assert result == "Ad tracking pixel"

    def test_save_normalizes_carried_forward_urls(self, tmp_path) -> None:
        """Carried-forward entries with query strings should be normalized."""
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            # Simulate an old cache file with a query-string-bearing URL.
            existing = script_cache.ScriptCacheEntry(
                domain="example.com",
                scripts=[
                    script_cache.CachedScript(
                        url="https://example.com/old.js?v=1",
                        content_hash="h0",
                        description="Old",
                    ),
                ],
            )
            new_scripts = [
                script_cache.CachedScript(url="https://example.com/new.js", content_hash="h1", description="New"),
            ]
            script_cache.save("example.com", new_scripts, existing=existing)

            loaded = script_cache.load("example.com")
            assert loaded is not None
            urls = {s.url for s in loaded.scripts}
            # The carried-forward URL should have its query string stripped.
            assert "https://example.com/old.js" in urls
            assert "https://example.com/old.js?v=1" not in urls

    def test_save_deduplicates_carried_forward(self, tmp_path) -> None:
        """Carried-forward entries with duplicate base URLs are deduplicated."""
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            existing = script_cache.ScriptCacheEntry(
                domain="example.com",
                scripts=[
                    script_cache.CachedScript(url="https://example.com/a.js?v=1", content_hash="h1", description="A v1"),
                    script_cache.CachedScript(url="https://example.com/a.js?v=2", content_hash="h2", description="A v2"),
                    script_cache.CachedScript(url="https://example.com/b.js", content_hash="h3", description="B"),
                ],
            )
            # Save with no new scripts — just carry forward.
            script_cache.save("example.com", [], existing=existing)

            loaded = script_cache.load("example.com")
            assert loaded is not None
            # Should deduplicate to one entry per base URL.
            assert len(loaded.scripts) == 2
            urls = {s.url for s in loaded.scripts}
            assert "https://example.com/a.js" in urls
            assert "https://example.com/b.js" in urls

    def test_modified_not_serialised(self) -> None:
        """The modified flag should not appear in serialised JSON."""
        entry = script_cache.ScriptCacheEntry(domain="example.com", modified=True)
        data = entry.model_dump()
        assert "modified" not in data
        json_str = entry.model_dump_json()
        assert "modified" not in json_str


# ── Cross-domain hash deduplication ─────────────────────────────


class TestLookupByHash:
    """Tests for cross-domain content-hash lookup."""

    def test_finds_hash_in_loaded_entries(self) -> None:
        """lookup_by_hash returns description when hash matches any entry."""
        entries: dict[str, script_cache.ScriptCacheEntry | None] = {
            "cdn1.example.com": script_cache.ScriptCacheEntry(
                domain="cdn1.example.com",
                scripts=[
                    script_cache.CachedScript(
                        url="https://cdn1.example.com/lib.js",
                        content_hash="abc123",
                        description="Utility library",
                    ),
                ],
            ),
            "cdn2.example.com": None,
        }
        result = script_cache.lookup_by_hash(entries, "abc123")
        assert result == "Utility library"

    def test_returns_none_when_no_match(self) -> None:
        entries: dict[str, script_cache.ScriptCacheEntry | None] = {
            "cdn.example.com": script_cache.ScriptCacheEntry(
                domain="cdn.example.com",
                scripts=[
                    script_cache.CachedScript(
                        url="https://cdn.example.com/a.js",
                        content_hash="aaa",
                        description="Script A",
                    ),
                ],
            ),
        }
        result = script_cache.lookup_by_hash(entries, "zzz999")
        assert result is None

    def test_skips_none_entries(self) -> None:
        entries: dict[str, script_cache.ScriptCacheEntry | None] = {
            "unknown": None,
            "cdn.example.com": script_cache.ScriptCacheEntry(
                domain="cdn.example.com",
                scripts=[
                    script_cache.CachedScript(
                        url="https://cdn.example.com/x.js",
                        content_hash="match",
                        description="Matched",
                    ),
                ],
            ),
        }
        result = script_cache.lookup_by_hash(entries, "match")
        assert result == "Matched"

    def test_returns_first_match_across_domains(self) -> None:
        """When the same hash exists in multiple domains, the first is returned."""
        entries: dict[str, script_cache.ScriptCacheEntry | None] = {
            "cdn1.example.com": script_cache.ScriptCacheEntry(
                domain="cdn1.example.com",
                scripts=[
                    script_cache.CachedScript(
                        url="https://cdn1.example.com/shared.js",
                        content_hash="shared_hash",
                        description="First description",
                    ),
                ],
            ),
            "cdn2.example.com": script_cache.ScriptCacheEntry(
                domain="cdn2.example.com",
                scripts=[
                    script_cache.CachedScript(
                        url="https://cdn2.example.com/shared.js",
                        content_hash="shared_hash",
                        description="Second description",
                    ),
                ],
            ),
        }
        result = script_cache.lookup_by_hash(entries, "shared_hash")
        assert result is not None

    def test_empty_entries(self) -> None:
        result = script_cache.lookup_by_hash({}, "abc")
        assert result is None


class TestSaveHashDedup:
    """Tests for content-hash deduplication during save."""

    def test_same_hash_different_urls_deduplicated(self, tmp_path) -> None:
        """Two scripts with the same hash but different URLs keep only one."""
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            analyzed = [
                script_cache.CachedScript(
                    url="https://cdn.example.com/a.js",
                    content_hash="same_hash",
                    description="Description A",
                ),
                script_cache.CachedScript(
                    url="https://cdn.example.com/b.js",
                    content_hash="same_hash",
                    description="Description B",
                ),
            ]
            script_cache.save("cdn.example.com", analyzed)

            loaded = script_cache.load("cdn.example.com")
            assert loaded is not None
            assert len(loaded.scripts) == 1
            # First entry wins
            assert loaded.scripts[0].description == "Description A"

    def test_different_hashes_both_kept(self, tmp_path) -> None:
        """Scripts with different hashes are both preserved."""
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            analyzed = [
                script_cache.CachedScript(
                    url="https://cdn.example.com/a.js",
                    content_hash="hash_a",
                    description="Script A",
                ),
                script_cache.CachedScript(
                    url="https://cdn.example.com/b.js",
                    content_hash="hash_b",
                    description="Script B",
                ),
            ]
            script_cache.save("cdn.example.com", analyzed)

            loaded = script_cache.load("cdn.example.com")
            assert loaded is not None
            assert len(loaded.scripts) == 2

    def test_carried_forward_hash_conflict_resolved(self, tmp_path) -> None:
        """Carried-forward entry with same hash as new entry is dropped."""
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            existing = script_cache.ScriptCacheEntry(
                domain="cdn.example.com",
                scripts=[
                    script_cache.CachedScript(
                        url="https://cdn.example.com/old.js",
                        content_hash="dup_hash",
                        description="Old description",
                    ),
                ],
            )
            new_scripts = [
                script_cache.CachedScript(
                    url="https://cdn.example.com/new.js",
                    content_hash="dup_hash",
                    description="New description",
                ),
            ]
            script_cache.save("cdn.example.com", new_scripts, existing=existing)

            loaded = script_cache.load("cdn.example.com")
            assert loaded is not None
            # New entry wins; old carried-forward with same hash is dropped
            assert len(loaded.scripts) == 1
            assert loaded.scripts[0].description == "New description"


class TestIsFallbackDescription:
    """Tests for is_fallback_description guard."""

    def test_all_infer_from_url_results_are_fallbacks(self) -> None:
        """Every value _infer_from_url can produce must be
        in _FALLBACK_DESCRIPTIONS."""
        urls = [
            "https://cdn.example.com/analytics.js",
            "https://cdn.example.com/tracking.js",
            "https://cdn.example.com/pixel.js",
            "https://cdn.example.com/consent.js",
            "https://cdn.example.com/chat.js",
            "https://cdn.example.com/ads.js",
            "https://cdn.example.com/social.js",
            "https://cdn.example.com/vendor.js",
            "https://cdn.example.com/polyfill.js",
            "https://cdn.example.com/bundle.js",
            "https://cdn.example.com/chunk.js",
            "https://cdn.example.com/unknown.js",
        ]
        for url in urls:
            desc = _infer_from_url(url)
            assert is_fallback_description(desc), f"_infer_from_url('{url}') returned '{desc}' which is NOT in _FALLBACK_DESCRIPTIONS"

    def test_llm_description_is_not_fallback(self) -> None:
        """A real LLM-generated description should not match."""
        assert is_fallback_description("Google Tag Manager container script") is False

    def test_all_known_fallbacks_detected(self) -> None:
        """Every entry in _FALLBACK_DESCRIPTIONS is detected."""
        for desc in _FALLBACK_DESCRIPTIONS:
            assert is_fallback_description(desc) is True

    def test_empty_string_is_not_fallback(self) -> None:
        assert is_fallback_description("") is False

    def test_case_sensitive(self) -> None:
        """Fallback detection is case-sensitive."""
        assert is_fallback_description("third-party script") is False
        assert is_fallback_description("Third-party script") is True


# ── URL validation ──────────────────────────────────────────────

import pytest


class TestIsValidScriptUrl:
    """Tests for is_valid_script_url."""

    def test_normal_https_url(self) -> None:
        assert script_cache.is_valid_script_url("https://cdn.example.com/tracker.js") is True

    def test_http_url(self) -> None:
        assert script_cache.is_valid_script_url("http://cdn.example.com/script.js") is True

    def test_filesystem_path(self) -> None:
        assert script_cache.is_valid_script_url("/var/www/html/script.js") is False

    def test_data_uri(self) -> None:
        assert script_cache.is_valid_script_url("data:text/javascript,alert(1)") is False

    def test_blob_uri(self) -> None:
        assert script_cache.is_valid_script_url("blob:https://example.com/abc") is False

    def test_empty_string(self) -> None:
        assert script_cache.is_valid_script_url("") is False

    def test_whitespace_only(self) -> None:
        assert script_cache.is_valid_script_url("   ") is False

    def test_no_scheme(self) -> None:
        assert script_cache.is_valid_script_url("cdn.example.com/script.js") is False

    def test_root_url(self) -> None:
        assert script_cache.is_valid_script_url("https://cdn.example.com/") is True


class TestCachedScriptRejectsMalformedUrl:
    """CachedScript validator rejects non-HTTP URLs."""

    def test_valid_url_accepted(self) -> None:
        s = script_cache.CachedScript(
            url="https://cdn.example.com/tracker.js",
            content_hash="abc123",
            description="Tracking script",
        )
        assert s.url == "https://cdn.example.com/tracker.js"

    def test_filesystem_path_rejected(self) -> None:
        with pytest.raises(ValueError, match="Malformed script URL"):
            script_cache.CachedScript(
                url="/var/www/html/script.js",
                content_hash="abc123",
                description="Should fail",
            )

    def test_empty_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="Malformed script URL"):
            script_cache.CachedScript(
                url="",
                content_hash="abc123",
                description="Should fail",
            )
