"""Tests for src.utils.cache — atomic writes and cache management."""

from __future__ import annotations

import pathlib

from src.utils.cache import atomic_write_text, clear_all


class TestAtomicWriteText:
    """Tests for atomic_write_text()."""

    def test_writes_content(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "test.json"
        atomic_write_text(target, '{"key": "value"}')
        assert target.read_text(encoding="utf-8") == '{"key": "value"}'

    def test_creates_parent_dirs(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "sub" / "dir" / "test.json"
        atomic_write_text(target, "content")
        assert target.read_text(encoding="utf-8") == "content"

    def test_overwrites_existing_file(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "test.json"
        target.write_text("old", encoding="utf-8")
        atomic_write_text(target, "new")
        assert target.read_text(encoding="utf-8") == "new"


class TestClearAll:
    """Tests for clear_all()."""

    def test_clear_with_files(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        monkeypatch.setattr("src.utils.cache._CACHE_ROOT", tmp_path)
        sub = tmp_path / "domain"
        sub.mkdir()
        (sub / "example.json").write_text("{}", encoding="utf-8")
        (sub / "test.json").write_text("{}", encoding="utf-8")
        removed = clear_all()
        assert removed == 2
        assert sub.exists()
        assert list(sub.iterdir()) == []

    def test_clear_empty_cache(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        monkeypatch.setattr("src.utils.cache._CACHE_ROOT", tmp_path)
        sub = tmp_path / "domain"
        sub.mkdir()
        removed = clear_all()
        assert removed == 0

    def test_clear_nonexistent_cache(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        monkeypatch.setattr("src.utils.cache._CACHE_ROOT", tmp_path / "nonexistent")
        removed = clear_all()
        assert removed == 0

    def test_clear_root_level_files(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        monkeypatch.setattr("src.utils.cache._CACHE_ROOT", tmp_path)
        (tmp_path / "stray.txt").write_text("stray", encoding="utf-8")
        removed = clear_all()
        assert removed == 1

    def test_clear_multiple_subdirs(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        monkeypatch.setattr("src.utils.cache._CACHE_ROOT", tmp_path)
        for name in ("domain", "overlay", "scripts"):
            sub = tmp_path / name
            sub.mkdir()
            (sub / "test.json").write_text("{}", encoding="utf-8")
        removed = clear_all()
        assert removed == 3
