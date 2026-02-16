"""Tests for 'unknown' domain guards in cache modules.

When ``extract_domain()`` returns ``"unknown"`` (e.g. for
malformed URLs), caches must refuse to load or save so that
unrelated analyses don't share or corrupt a single
``unknown.json`` file.
"""

from __future__ import annotations

from unittest.mock import patch

from src.analysis import domain_cache, script_cache
from src.consent import overlay_cache


# ── domain_cache ────────────────────────────────────────────────


class TestDomainCacheUnknownGuard:
    """domain_cache should short-circuit for 'unknown' domains."""

    def test_load_returns_none(self, tmp_path) -> None:
        with patch.object(domain_cache, "_CACHE_DIR", tmp_path):
            # Even if a file exists, load must refuse.
            (tmp_path / "unknown.json").write_text("{}", encoding="utf-8")
            assert domain_cache.load("unknown") is None

    def test_save_is_noop(self, tmp_path) -> None:
        from src.models import report

        sr = report.StructuredReport(
            tracking_technologies=report.TrackingTechnologiesSection(
                analytics=[
                    report.TrackerEntry(
                        name="GA4",
                        domains=["google-analytics.com"],
                        purpose="Analytics",
                    ),
                ],
            ),
            cookie_analysis=report.CookieAnalysisSection(
                total=1,
                groups=[],
            ),
            key_vendors=report.VendorSection(vendors=[]),
            data_collection=report.DataCollectionSection(items=[]),
        )
        with patch.object(domain_cache, "_CACHE_DIR", tmp_path):
            domain_cache.save_from_report("unknown", sr)
            # No file should have been written.
            assert not (tmp_path / "unknown.json").exists()


# ── script_cache ────────────────────────────────────────────────


class TestScriptCacheUnknownGuard:
    """script_cache should short-circuit for 'unknown' domains."""

    def test_load_returns_none(self, tmp_path) -> None:
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            (tmp_path / "unknown.json").write_text("{}", encoding="utf-8")
            assert script_cache.load("unknown") is None

    def test_save_is_noop(self, tmp_path) -> None:
        with patch.object(script_cache, "_CACHE_DIR", tmp_path):
            script_cache.save("unknown", [])
            assert not (tmp_path / "unknown.json").exists()


# ── overlay_cache ───────────────────────────────────────────────


class TestOverlayCacheUnknownGuard:
    """overlay_cache should short-circuit for 'unknown' domains."""

    def test_load_returns_none(self, tmp_path) -> None:
        with patch.object(overlay_cache, "_CACHE_DIR", tmp_path):
            (tmp_path / "unknown.json").write_text("{}", encoding="utf-8")
            assert overlay_cache.load("unknown") is None

    def test_save_is_noop(self, tmp_path) -> None:
        entry = overlay_cache.OverlayCacheEntry(
            domain="unknown",
            overlays=[],
        )
        with patch.object(overlay_cache, "_CACHE_DIR", tmp_path):
            overlay_cache.save(entry)
            assert not (tmp_path / "unknown.json").exists()
