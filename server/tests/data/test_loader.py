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


class TestGetMediaGroups:
    """Tests for media group profile loading."""

    def test_loads_dict(self) -> None:
        groups = loader.get_media_groups()
        assert isinstance(groups, dict)
        assert len(groups) > 0

    def test_cached(self) -> None:
        a = loader.get_media_groups()
        b = loader.get_media_groups()
        assert a is b

    def test_values_are_media_group_profiles(self) -> None:
        from src.models.partners import MediaGroupProfile

        for profile in loader.get_media_groups().values():
            assert isinstance(profile, MediaGroupProfile)

    def test_known_groups_present(self) -> None:
        groups = loader.get_media_groups()
        expected = ["reach plc", "dmg media", "bbc", "news uk", "guardian media group", "financial times"]
        for name in expected:
            assert name in groups, f"Expected media group '{name}' not found"

    def test_profiles_have_required_fields(self) -> None:
        for name, profile in loader.get_media_groups().items():
            assert profile.parent, f"{name}: missing parent"
            assert profile.privacy_policy, f"{name}: missing privacy_policy"
            assert len(profile.properties) > 0, f"{name}: no properties"
            assert len(profile.domains) > 0, f"{name}: no domains"
            assert profile.consent_platform, f"{name}: missing consent_platform"
            assert len(profile.key_vendors) > 0, f"{name}: no key_vendors"
            assert len(profile.privacy_characteristics) > 0, f"{name}: no privacy_characteristics"

    def test_domains_are_lowercase(self) -> None:
        for name, profile in loader.get_media_groups().items():
            for domain in profile.domains:
                assert domain == domain.lower(), f"{name}: domain '{domain}' should be lowercase"


class TestFindMediaGroupByDomain:
    """Tests for domain-based media group lookup."""

    def test_known_domain(self) -> None:
        result = loader.find_media_group_by_domain("thesun.co.uk")
        assert result is not None
        name, profile = result
        assert name == "news uk"
        assert "The Sun" in profile.properties

    def test_unknown_domain_returns_none(self) -> None:
        result = loader.find_media_group_by_domain("example.com")
        assert result is None

    def test_case_insensitive(self) -> None:
        result = loader.find_media_group_by_domain("BBC.co.uk")
        assert result is not None
        assert result[0] == "bbc"

    def test_whitespace_stripped(self) -> None:
        result = loader.find_media_group_by_domain("  theguardian.com  ")
        assert result is not None
        assert result[0] == "guardian media group"

    def test_reach_domain(self) -> None:
        result = loader.find_media_group_by_domain("bristolpost.co.uk")
        assert result is not None
        assert result[0] == "reach plc"

    def test_ft_domain(self) -> None:
        result = loader.find_media_group_by_domain("ft.com")
        assert result is not None
        assert result[0] == "financial times"


class TestBuildMediaGroupContext:
    """Tests for URL-based media group context builder."""

    def test_known_url_returns_context(self) -> None:
        ctx = loader.build_media_group_context("https://www.bristolpost.co.uk/news/some-article")
        assert "Reach plc" in ctx
        assert "Prior Research" in ctx
        assert "Key Vendors" in ctx
        assert "Privacy Characteristics" in ctx

    def test_unknown_url_returns_empty(self) -> None:
        ctx = loader.build_media_group_context("https://www.example.com/page")
        assert ctx == ""

    def test_includes_vendor_list(self) -> None:
        ctx = loader.build_media_group_context("https://www.thesun.co.uk/")
        assert "Ozone Project" in ctx
        assert "LiveRamp" in ctx

    def test_includes_consent_platform(self) -> None:
        ctx = loader.build_media_group_context("https://www.theguardian.com/uk")
        assert "Sourcepoint" in ctx

    def test_includes_privacy_characteristics(self) -> None:
        ctx = loader.build_media_group_context("https://www.bbc.co.uk/news")
        assert "Privacy Characteristics" in ctx


class TestBuildTrackingCookieContext:
    """Tests for the known tracking cookie reference context builder."""

    def test_returns_non_empty_string(self) -> None:
        ctx = loader.build_tracking_cookie_context()
        assert isinstance(ctx, str)
        assert len(ctx) > 0

    def test_contains_heading(self) -> None:
        ctx = loader.build_tracking_cookie_context()
        assert "## Known Tracking Cookie Reference" in ctx

    def test_contains_platform_sections(self) -> None:
        ctx = loader.build_tracking_cookie_context()
        assert "### Google Analytics" in ctx
        assert "### Facebook" in ctx or "### Meta" in ctx

    def test_contains_known_cookies(self) -> None:
        ctx = loader.build_tracking_cookie_context()
        assert "_ga" in ctx
        assert "_fbp" in ctx
        assert "_hjid" in ctx

    def test_contains_purpose_labels(self) -> None:
        ctx = loader.build_tracking_cookie_context()
        assert "analytics" in ctx
        assert "advertising" in ctx

    def test_contains_risk_level_section(self) -> None:
        ctx = loader.build_tracking_cookie_context()
        assert "### Cookie Purpose Risk Levels" in ctx
        assert "analytics:" in ctx or "advertising:" in ctx


class TestTrackerDomains:
    """Tests for tracker domain loading."""

    def test_loads_dict(self) -> None:
        domains = loader.get_tracker_domains()
        assert isinstance(domains, dict)
        assert len(domains) > 0

    def test_cached(self) -> None:
        a = loader.get_tracker_domains()
        b = loader.get_tracker_domains()
        assert a is b

    def test_values_are_block_or_cookieblock(self) -> None:
        domains = loader.get_tracker_domains()
        for domain, action in list(domains.items())[:100]:
            assert action in ("block", "cookieblock"), f"{domain}: unexpected action '{action}'"

    def test_known_tracker_present(self) -> None:
        domains = loader.get_tracker_domains()
        assert "doubleclick.net" in domains

    def test_partner_domain_present(self) -> None:
        domains = loader.get_tracker_domains()
        assert "fingerprint.com" in domains
        assert domains["fingerprint.com"] == "cookieblock"

    def test_is_known_tracker_domain_exact(self) -> None:
        assert loader.is_known_tracker_domain("doubleclick.net") is True

    def test_is_known_tracker_domain_unknown(self) -> None:
        assert (
            loader.is_known_tracker_domain(
                "this-is-not-a-tracker.example",
            )
            is False
        )


class TestCnameDomains:
    """Tests for CNAME-cloaked domain loading."""

    def test_loads_dict(self) -> None:
        domains = loader.get_cname_domains()
        assert isinstance(domains, dict)
        assert len(domains) > 0

    def test_cached(self) -> None:
        a = loader.get_cname_domains()
        b = loader.get_cname_domains()
        assert a is b

    def test_no_metadata_keys(self) -> None:
        domains = loader.get_cname_domains()
        for key in domains:
            assert not key.startswith("_"), f"Metadata key '{key}' should be filtered out"

    def test_values_are_strings(self) -> None:
        domains = loader.get_cname_domains()
        for key, val in list(domains.items())[:100]:
            assert isinstance(val, str), f"{key}: expected str, got {type(val)}"

    def test_get_cname_target_known(self) -> None:
        # Use a stable entry from the dataset
        domains = loader.get_cname_domains()
        first_key = next(iter(domains))
        target = loader.get_cname_target(first_key)
        assert target == domains[first_key]

    def test_get_cname_target_unknown(self) -> None:
        target = loader.get_cname_target("not-cloaked.example.com")
        assert target is None


class TestDisconnectServices:
    """Tests for Disconnect tracking protection data."""

    def test_loads_dict(self) -> None:
        services = loader.get_disconnect_services()
        assert isinstance(services, dict)
        assert len(services) > 0

    def test_cached(self) -> None:
        a = loader.get_disconnect_services()
        b = loader.get_disconnect_services()
        assert a is b

    def test_entries_have_category(self) -> None:
        services = loader.get_disconnect_services()
        for domain, info in list(services.items())[:100]:
            assert "category" in info, f"{domain}: missing 'category'"

    def test_entries_have_company(self) -> None:
        services = loader.get_disconnect_services()
        for domain, info in list(services.items())[:100]:
            assert "company" in info, f"{domain}: missing 'company'"

    def test_known_tracker_present(self) -> None:
        services = loader.get_disconnect_services()
        assert "doubleclick.net" in services

    def test_get_disconnect_category_known(self) -> None:
        category = loader.get_disconnect_category("doubleclick.net")
        assert category is not None

    def test_get_disconnect_category_unknown(self) -> None:
        category = loader.get_disconnect_category(
            "not-a-tracker.example",
        )
        assert category is None

    def test_build_disconnect_context_with_known_domains(self) -> None:
        ctx = loader.build_disconnect_context(["doubleclick.net"])
        assert "## Known Tracker Domain Classifications (Disconnect)" in ctx
        assert "doubleclick.net" in ctx
        assert "→" in ctx

    def test_build_disconnect_context_groups_by_category(self) -> None:
        ctx = loader.build_disconnect_context(
            ["doubleclick.net", "scorecardresearch.com"],
        )
        assert "###" in ctx

    def test_build_disconnect_context_empty_for_unknown(self) -> None:
        ctx = loader.build_disconnect_context(
            ["not-a-tracker.example"],
        )
        assert ctx == ""

    def test_build_disconnect_context_empty_for_empty_list(self) -> None:
        ctx = loader.build_disconnect_context([])
        assert ctx == ""


class TestGetDomainDescription:
    def test_disconnect_domain_returns_category_and_company(self) -> None:
        result = loader.get_domain_description("doubleclick.net")
        assert result["description"] is not None
        assert "Google" in (result["company"] or "")

    def test_tracker_domain_returns_known_tracking(self) -> None:
        """A domain in tracker-domains but not in Disconnect should get a
        generic 'Known tracking domain' description."""
        # Find a domain only in tracker-domains, not in disconnect
        tracker_domains = loader.get_tracker_domains()
        disconnect = loader.get_disconnect_services()
        only_tracker = None
        for domain in tracker_domains:
            if domain not in disconnect:
                only_tracker = domain
                break
        if only_tracker is None:
            pytest.skip("No tracker-only domain found for testing")
        result = loader.get_domain_description(only_tracker)
        assert result["description"] == "Known tracking domain"

    def test_unknown_domain_returns_none(self) -> None:
        result = loader.get_domain_description("not-a-real-tracker-xyzzy.example")
        assert result["company"] is None
        assert result["description"] is None


class TestGetStorageKeyHint:
    def test_known_ga_key(self) -> None:
        result = loader.get_storage_key_hint("_ga")
        assert result["setBy"] is not None
        assert "Google" in result["setBy"]
        assert result["description"] is not None

    def test_unknown_key_returns_nones(self) -> None:
        result = loader.get_storage_key_hint("my_custom_app_setting_12345")
        assert result["setBy"] is None
        assert result["description"] is None

    def test_pattern_prefix_match(self) -> None:
        """_ga_ prefixed keys should match the GA4 pattern."""
        result = loader.get_storage_key_hint("_ga_ABC123")
        assert result["setBy"] is not None
        assert result["description"] is not None
