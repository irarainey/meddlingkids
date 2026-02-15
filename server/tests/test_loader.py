"""Tests for src.data.loader — JSON data loading and caching."""

from __future__ import annotations

import re

import pytest

from src.data import loader
from src.models import partners


class TestLoadJson:
    def test_tracking_scripts_file_exists(self) -> None:
        """Verify the tracking-scripts.json file loads without error."""
        data = loader._load_json("trackers/tracking-scripts.json")
        assert isinstance(data, list)
        assert len(data) > 0

    def test_benign_scripts_file_exists(self) -> None:
        data = loader._load_json("trackers/benign-scripts.json")
        assert isinstance(data, list)

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            loader._load_json("nonexistent/file.json")


class TestGetTrackingScripts:
    def test_returns_script_patterns(self) -> None:
        scripts = loader.get_tracking_scripts()
        assert isinstance(scripts, list)
        assert all(isinstance(s, partners.ScriptPattern) for s in scripts)

    def test_patterns_are_compiled(self) -> None:
        scripts = loader.get_tracking_scripts()
        for s in scripts:
            assert isinstance(s.compiled, re.Pattern)

    def test_cached(self) -> None:
        a = loader.get_tracking_scripts()
        b = loader.get_tracking_scripts()
        assert a is b


class TestGetBenignScripts:
    def test_returns_script_patterns(self) -> None:
        scripts = loader.get_benign_scripts()
        assert isinstance(scripts, list)
        assert all(isinstance(s, partners.ScriptPattern) for s in scripts)


class TestPartnerCategories:
    def test_non_empty(self) -> None:
        assert len(loader.PARTNER_CATEGORIES) > 0

    def test_all_are_category_config(self) -> None:
        for cat in loader.PARTNER_CATEGORIES:
            assert isinstance(cat, partners.PartnerCategoryConfig)
            assert cat.file.endswith(".json")

    def test_all_databases_loadable(self) -> None:
        for cat in loader.PARTNER_CATEGORIES:
            db = loader.get_partner_database(cat.file)
            assert isinstance(db, dict)
