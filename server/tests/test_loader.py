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


class TestGdprTcfData:
    """Tests for GDPR / TCF reference data loading."""

    def test_tcf_purposes_loads(self) -> None:
        data = loader.get_tcf_purposes()
        assert isinstance(data, dict)
        assert "purposes" in data
        assert "special_purposes" in data
        assert "features" in data
        assert "special_features" in data
        assert "data_declarations" in data

    def test_tcf_has_all_12_purposes(self) -> None:
        data = loader.get_tcf_purposes()
        purposes = data["purposes"]
        # TCF v2.2 defines 11 purposes (1-11)
        for i in range(1, 12):
            assert str(i) in purposes, f"Purpose {i} missing"
            assert "name" in purposes[str(i)]
            assert "description" in purposes[str(i)]

    def test_tcf_has_3_special_purposes(self) -> None:
        data = loader.get_tcf_purposes()
        sp = data["special_purposes"]
        for i in range(1, 4):
            assert str(i) in sp

    def test_tcf_has_3_features(self) -> None:
        data = loader.get_tcf_purposes()
        features = data["features"]
        for i in range(1, 4):
            assert str(i) in features

    def test_tcf_has_2_special_features(self) -> None:
        data = loader.get_tcf_purposes()
        sf = data["special_features"]
        for i in range(1, 3):
            assert str(i) in sf

    def test_tcf_purposes_cached(self) -> None:
        a = loader.get_tcf_purposes()
        b = loader.get_tcf_purposes()
        assert a is b

    def test_consent_cookies_loads(self) -> None:
        data = loader.get_consent_cookies()
        assert isinstance(data, dict)
        assert "tcf_cookies" in data
        assert "cmp_cookies" in data
        assert "consent_cookie_name_patterns" in data

    def test_consent_cookies_has_euconsent(self) -> None:
        data = loader.get_consent_cookies()
        assert "euconsent-v2" in data["tcf_cookies"]

    def test_consent_cookies_has_onetrust(self) -> None:
        data = loader.get_consent_cookies()
        assert "OptanonConsent" in data["cmp_cookies"]

    def test_consent_cookies_cached(self) -> None:
        a = loader.get_consent_cookies()
        b = loader.get_consent_cookies()
        assert a is b

    def test_gdpr_reference_loads(self) -> None:
        data = loader.get_gdpr_reference()
        assert isinstance(data, dict)
        assert "gdpr" in data
        assert "eprivacy_directive" in data
        assert "tcf_overview" in data

    def test_gdpr_has_lawful_bases(self) -> None:
        data = loader.get_gdpr_reference()
        bases = data["gdpr"]["lawful_bases"]
        assert "consent" in bases
        assert "legitimate_interest" in bases

    def test_gdpr_reference_cached(self) -> None:
        a = loader.get_gdpr_reference()
        b = loader.get_gdpr_reference()
        assert a is b

    def test_get_tcf_purpose_name_valid(self) -> None:
        name = loader.get_tcf_purpose_name(1)
        assert name == "Store and/or access information on a device"

    def test_get_tcf_purpose_name_invalid(self) -> None:
        name = loader.get_tcf_purpose_name(999)
        assert name == "Unknown purpose 999"

    def test_get_consent_cookie_names(self) -> None:
        names = loader.get_consent_cookie_names()
        assert isinstance(names, list)
        assert len(names) > 0
        assert "euconsent" in names
        assert "OptanonConsent" in names
        assert "usprivacy" in names
