"""Tests for src.utils.cache — cross-cache management."""

from __future__ import annotations

import pathlib
from unittest import mock

from src.utils import cache


class TestClearAll:
    """Tests for cache.clear_all()."""

    def test_returns_zero_when_no_cache_dir(self, tmp_path: pathlib.Path) -> None:
        nonexistent = tmp_path / "does_not_exist"
        with mock.patch.object(cache, "_CACHE_ROOT", nonexistent):
            assert cache.clear_all() == 0

    def test_clears_files_in_subdirectories(self, tmp_path: pathlib.Path) -> None:
        sub = tmp_path / "overlays"
        sub.mkdir()
        (sub / "a.json").write_text("{}")
        (sub / "b.json").write_text("{}")

        with mock.patch.object(cache, "_CACHE_ROOT", tmp_path):
            count = cache.clear_all()

        assert count == 2
        # Subdirectory should be recreated but empty
        assert sub.exists()
        assert list(sub.iterdir()) == []

    def test_clears_files_at_root_level(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "stale.json").write_text("{}")

        with mock.patch.object(cache, "_CACHE_ROOT", tmp_path):
            count = cache.clear_all()

        assert count == 1

    def test_returns_zero_for_empty_cache(self, tmp_path: pathlib.Path) -> None:
        sub = tmp_path / "empty_dir"
        sub.mkdir()

        with mock.patch.object(cache, "_CACHE_ROOT", tmp_path):
            assert cache.clear_all() == 0

    def test_clears_multiple_subdirectories(self, tmp_path: pathlib.Path) -> None:
        for name in ("overlays", "scripts", "domains"):
            d = tmp_path / name
            d.mkdir()
            (d / "data.json").write_text("{}")

        with mock.patch.object(cache, "_CACHE_ROOT", tmp_path):
            count = cache.clear_all()

        assert count == 3
