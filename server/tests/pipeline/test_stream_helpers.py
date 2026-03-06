"""Tests for src.pipeline.stream — consent string discovery."""

from __future__ import annotations

import dataclasses

from src.pipeline.stream import _discover_consent_string


@dataclasses.dataclass(frozen=True, slots=True)
class _MockTiers:
    """Minimal mock tiers for testing _discover_consent_string."""

    cookie_label: str = "test_cookie"
    _cookie_result: str | None = None
    _storage_result: tuple[str, str] | None = None
    _profile_result: tuple[str, str] | None = None
    _json_result: tuple[str, str] | None = None
    _scan_result: tuple[str, str] | None = None
    _scan_json_result: tuple[str, str] | None = None

    def find_in_cookies(self, cookies):
        return self._cookie_result

    def find_in_storage(self, storage):
        return self._storage_result

    def find_by_profile(self, cookies, storage, sources):
        return self._profile_result

    def find_in_json_storage(self, storage):
        return self._json_result

    def scan(self, cookies, storage):
        return self._scan_result

    def scan_json(self, storage):
        return self._scan_json_result


class TestDiscoverConsentString:
    """Tests for _discover_consent_string()."""

    def test_tier_1_cookie(self) -> None:
        tiers = _MockTiers(cookie_label="euconsent-v2", _cookie_result="ABCDE")
        result = _discover_consent_string(tiers, [], [], {})  # type: ignore[arg-type]
        assert result == ("euconsent-v2", "ABCDE")

    def test_tier_1_storage(self) -> None:
        tiers = _MockTiers(_storage_result=("tc_key", "FGHIJ"))
        result = _discover_consent_string(tiers, [], [], {})  # type: ignore[arg-type]
        assert result == ("localStorage[tc_key]", "FGHIJ")

    def test_tier_2_profile(self) -> None:
        tiers = _MockTiers(_profile_result=("profile_source", "KLMNO"))
        result = _discover_consent_string(tiers, [], [], {"cookie": ["euconsent"]})  # type: ignore[arg-type]
        assert result == ("profile_source", "KLMNO")

    def test_tier_2_skipped_without_sources(self) -> None:
        tiers = _MockTiers(_profile_result=("profile_source", "KLMNO"))
        result = _discover_consent_string(tiers, [], [], {})  # type: ignore[arg-type]
        # Tier 2 skipped because tc_sources is empty
        assert result is None

    def test_tier_3_json(self) -> None:
        tiers = _MockTiers(_json_result=("json_key", "PQRST"))
        result = _discover_consent_string(tiers, [], [], {})  # type: ignore[arg-type]
        assert result == ("json_key", "PQRST")

    def test_tier_4_scan(self) -> None:
        tiers = _MockTiers(_scan_result=("scan_source", "UVWXY"))
        result = _discover_consent_string(tiers, [], [], {})  # type: ignore[arg-type]
        assert result == ("scan_source", "UVWXY")

    def test_tier_5_scan_json(self) -> None:
        tiers = _MockTiers(_scan_json_result=("json_scan", "ZZZZZ"))
        result = _discover_consent_string(tiers, [], [], {})  # type: ignore[arg-type]
        assert result == ("json_scan", "ZZZZZ")

    def test_no_match_returns_none(self) -> None:
        tiers = _MockTiers()
        result = _discover_consent_string(tiers, [], [], {})  # type: ignore[arg-type]
        assert result is None

    def test_priority_cookie_over_storage(self) -> None:
        tiers = _MockTiers(
            cookie_label="cookie",
            _cookie_result="FROM_COOKIE",
            _storage_result=("key", "FROM_STORAGE"),
        )
        result = _discover_consent_string(tiers, [], [], {})  # type: ignore[arg-type]
        assert result == ("cookie", "FROM_COOKIE")
