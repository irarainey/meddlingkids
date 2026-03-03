"""Tests for the IAB TCF v2 TC String decoder."""

from __future__ import annotations

from src.analysis import tc_string

# ====================================================================
# Known TC strings for testing
# ====================================================================

# Minimal TC string with all 10 purposes consented, no vendors.
# CMP 68, GVL v187, language EN, country GB.
_TC_MINIMAL = "CPokAsAPokAsABEACBENC7CgAP_AAH_AAAwIAAAAAAAA"

# Real-world TC string with broad consent: 11 purposes, 945 vendors,
# LI for 6 purposes, CMP 300, country US.
_TC_BROAD = (
    "CQIwkgAQIwkgAEsABBENBeFsAP_gAEPgACiQKNNd_X__bX9n-_7_6ft0cY1f9_r3v"
    "-QzjhfNs-8F3L_W_LwX_2E7NF36tq4KmR4ku1LBIUNtHMnUDUmxaolVrzHsak2cpyN"
    "KJ7LkmnsZe2dYGHtPn9lD-YKZ7_5_9_f52T_9_9_-39z3_9f___dt-_-__-ljf-_5_"
    "_3_3_vp_-_P___5_7_6_9______9_P___9v-_8_________7_v_9____9_r9________"
    "___w_8IAAA"
)


class TestBitReader:
    """Tests for the low-level bit reader."""

    def test_read_int(self) -> None:
        reader = tc_string._BitReader(b"\xa5")  # 10100101
        assert reader.read_int(4) == 0b1010
        assert reader.read_int(4) == 0b0101

    def test_read_bool(self) -> None:
        reader = tc_string._BitReader(b"\x80")  # 10000000
        assert reader.read_bool() is True
        assert reader.read_bool() is False

    def test_read_bitfield(self) -> None:
        reader = tc_string._BitReader(b"\b0")  # 00001000 00110000
        # 5 bits = 00001 → ID 5 is set
        ids = reader.read_bitfield(5)
        assert ids == [5]

    def test_read_string(self) -> None:
        # A=0 (000000), B=1 (000001) → 12 bits = 000000 000001
        # Packed: 00000000 0001xxxx → 0x00 0x10
        reader = tc_string._BitReader(b"\x00\x10")
        result = reader.read_string(2)
        assert result == "AB"

    def test_remaining(self) -> None:
        reader = tc_string._BitReader(b"\xff")
        assert reader.remaining == 8
        reader.read_int(3)
        assert reader.remaining == 5

    def test_read_int_past_end_returns_zero(self) -> None:
        reader = tc_string._BitReader(b"\xff")
        reader.read_int(8)
        assert reader.read_int(4) == 0


class TestDecodeTimestamp:
    """Tests for TCF timestamp decoding."""

    def test_zero_returns_epoch(self) -> None:
        result = tc_string._decode_timestamp(0)
        assert "2000-01-01" in result

    def test_recent_timestamp(self) -> None:
        # 10 deciseconds = 1 second after epoch
        result = tc_string._decode_timestamp(10)
        assert "2000-01-01T00:00:01" in result


class TestBase64UrlDecode:
    """Tests for Base64url decoding with padding correction."""

    def test_normal_string(self) -> None:
        data = tc_string._base64url_decode("AAAA")
        assert data == b"\x00\x00\x00"

    def test_padding_correction(self) -> None:
        # Base64 strings without padding should still decode
        data = tc_string._base64url_decode("AA")
        assert len(data) > 0


class TestDecodeTcString:
    """Tests for full TC string decoding."""

    def test_minimal_tc_string(self) -> None:
        result = tc_string.decode_tc_string(_TC_MINIMAL)
        assert result is not None
        assert result.version == 2
        assert result.cmp_id == 68
        assert result.consent_language == "EN"
        assert result.publisher_country_code == "GB"
        assert result.vendor_list_version == 187
        assert result.purpose_consents == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        assert result.vendor_consent_count == 0

    def test_minimal_purpose_li(self) -> None:
        result = tc_string.decode_tc_string(_TC_MINIMAL)
        assert result is not None
        # Purposes 2-10 have LI (purpose 1 never has LI)
        assert result.purpose_legitimate_interests == [2, 3, 4, 5, 6, 7, 8, 9, 10]

    def test_broad_consent_tc_string(self) -> None:
        result = tc_string.decode_tc_string(_TC_BROAD)
        assert result is not None
        assert result.version == 2
        assert result.cmp_id == 300
        assert result.consent_language == "EN"
        assert result.publisher_country_code == "US"
        assert result.is_service_specific is True
        # TCF v2.2 adds purpose 11
        assert 11 in result.purpose_consents
        assert result.total_purposes_consented == 11

    def test_broad_consent_vendor_counts(self) -> None:
        result = tc_string.decode_tc_string(_TC_BROAD)
        assert result is not None
        assert result.vendor_consent_count > 900
        assert result.vendor_li_count > 0

    def test_broad_consent_li_purposes(self) -> None:
        result = tc_string.decode_tc_string(_TC_BROAD)
        assert result is not None
        # Purpose 2 allows LI
        assert 2 in result.purpose_legitimate_interests

    def test_raw_string_preserved(self) -> None:
        result = tc_string.decode_tc_string(_TC_MINIMAL)
        assert result is not None
        assert result.raw_string == _TC_MINIMAL

    def test_none_for_empty_string(self) -> None:
        assert tc_string.decode_tc_string("") is None

    def test_none_for_short_string(self) -> None:
        assert tc_string.decode_tc_string("ABC") is None

    def test_none_for_garbage(self) -> None:
        assert tc_string.decode_tc_string("!@#$%^&*()") is None

    def test_none_for_invalid_version(self) -> None:
        # Version 0 is not valid — first 6 bits = 000000
        assert tc_string.decode_tc_string("AAAAAAAAAAAAAAAAAAAAAA") is None

    def test_multi_segment_decodes_core(self) -> None:
        # TC strings can have multiple segments separated by "."
        # Only the core (first) segment should be decoded.
        multi = f"{_TC_MINIMAL}.YAAAAAAAAAAAA"
        result = tc_string.decode_tc_string(multi)
        assert result is not None
        assert result.version == 2
        assert result.cmp_id == 68

    def test_model_dump_camel_case(self) -> None:
        result = tc_string.decode_tc_string(_TC_MINIMAL)
        assert result is not None
        data = result.model_dump(by_alias=True)
        assert "cmpId" in data
        assert "purposeConsents" in data
        assert "vendorListVersion" in data
        assert "vendorConsentCount" in data

    def test_special_feature_opt_ins(self) -> None:
        result = tc_string.decode_tc_string(_TC_MINIMAL)
        assert result is not None
        # This particular TC string has no special features
        assert isinstance(result.special_feature_opt_ins, list)


class TestFindTcStringInCookies:
    """Tests for finding TC strings in cookie lists."""

    def test_finds_euconsent_v2_cookie(self) -> None:
        cookies = [
            {"name": "other_cookie", "value": "abc"},
            {"name": "euconsent-v2", "value": _TC_MINIMAL},
        ]
        result = tc_string.find_tc_string_in_cookies(cookies)
        assert result == _TC_MINIMAL

    def test_returns_none_when_missing(self) -> None:
        cookies = [
            {"name": "other_cookie", "value": "abc"},
        ]
        assert tc_string.find_tc_string_in_cookies(cookies) is None

    def test_returns_none_for_empty_value(self) -> None:
        cookies = [
            {"name": "euconsent-v2", "value": ""},
        ]
        assert tc_string.find_tc_string_in_cookies(cookies) is None

    def test_returns_none_for_empty_list(self) -> None:
        assert tc_string.find_tc_string_in_cookies([]) is None

    def test_supports_object_access(self) -> None:
        """Cookie objects with attribute access (e.g. TrackedCookie)."""

        class FakeCookie:
            def __init__(self, name: str, value: str) -> None:
                self.name = name
                self.value = value

        cookies = [FakeCookie("euconsent-v2", _TC_MINIMAL)]
        result = tc_string.find_tc_string_in_cookies(cookies)  # type: ignore[arg-type]
        assert result == _TC_MINIMAL


# ====================================================================
# AC String decoding
# ====================================================================

# Example AC string: version 1, three ATP vendor IDs
_AC_SIMPLE = "1~1.35.70"

# Real-world-style AC string with many vendors
_AC_BROAD = "1~1.35.70.89.93.108.122.149.196.236.486.494.495.540.574.864.981"


class TestDecodeAcString:
    """Tests for AC String decoding."""

    def test_simple_ac_string(self) -> None:
        result = tc_string.decode_ac_string(_AC_SIMPLE)
        assert result is not None
        assert result.version == 1
        assert result.vendor_ids == [1, 35, 70]
        assert result.vendor_count == 3
        assert result.raw_string == _AC_SIMPLE

    def test_broad_ac_string(self) -> None:
        result = tc_string.decode_ac_string(_AC_BROAD)
        assert result is not None
        assert result.version == 1
        assert result.vendor_count == 17
        assert 1 in result.vendor_ids
        assert 981 in result.vendor_ids

    def test_empty_vendor_list(self) -> None:
        """AC string with version but no vendors."""
        result = tc_string.decode_ac_string("1~")
        assert result is not None
        assert result.version == 1
        assert result.vendor_ids == []
        assert result.vendor_count == 0

    def test_single_vendor(self) -> None:
        result = tc_string.decode_ac_string("1~42")
        assert result is not None
        assert result.vendor_ids == [42]
        assert result.vendor_count == 1

    def test_returns_none_for_empty_string(self) -> None:
        assert tc_string.decode_ac_string("") is None

    def test_returns_none_for_no_tilde(self) -> None:
        assert tc_string.decode_ac_string("1234") is None

    def test_returns_none_for_invalid_version(self) -> None:
        assert tc_string.decode_ac_string("abc~1.2.3") is None

    def test_returns_none_for_invalid_vendor_ids(self) -> None:
        assert tc_string.decode_ac_string("1~abc.def") is None

    def test_vendors_sorted(self) -> None:
        """Vendor IDs should be returned in sorted order."""
        result = tc_string.decode_ac_string("1~100.5.50.1")
        assert result is not None
        assert result.vendor_ids == [1, 5, 50, 100]

    def test_model_serialization(self) -> None:
        """AcStringData should serialize with camelCase aliases."""
        result = tc_string.decode_ac_string(_AC_SIMPLE)
        assert result is not None
        data = result.model_dump(by_alias=True)
        assert "vendorIds" in data
        assert "vendorCount" in data
        assert "rawString" in data
        assert data["vendorCount"] == 3


class TestFindAcStringInCookies:
    """Tests for finding AC String in cookies."""

    def test_finds_addtl_consent_cookie(self) -> None:
        cookies = [
            {"name": "other", "value": "abc"},
            {"name": "addtl_consent", "value": _AC_SIMPLE},
        ]
        assert tc_string.find_ac_string_in_cookies(cookies) == _AC_SIMPLE

    def test_returns_none_when_absent(self) -> None:
        cookies = [
            {"name": "euconsent-v2", "value": "CPok..."},
            {"name": "other_cookie", "value": "abc"},
        ]
        assert tc_string.find_ac_string_in_cookies(cookies) is None

    def test_returns_none_for_empty_value(self) -> None:
        cookies = [
            {"name": "addtl_consent", "value": ""},
        ]
        assert tc_string.find_ac_string_in_cookies(cookies) is None

    def test_returns_none_for_empty_list(self) -> None:
        assert tc_string.find_ac_string_in_cookies([]) is None

    def test_supports_object_access(self) -> None:
        """Cookie objects with attribute access."""

        class FakeCookie:
            def __init__(self, name: str, value: str) -> None:
                self.name = name
                self.value = value

        cookies = [FakeCookie("addtl_consent", _AC_SIMPLE)]
        result = tc_string.find_ac_string_in_cookies(cookies)  # type: ignore[arg-type]
        assert result == _AC_SIMPLE


# ====================================================================
# localStorage-based TC String lookup
# ====================================================================


class TestFindTcStringInStorage:
    """Tests for finding TC strings in localStorage items."""

    def test_finds_dmg_media_key(self) -> None:
        """DMG Media CMP stores TC string under mol.ads.cmp.tcf.tcstring."""
        items = [
            {"key": "other_key", "value": "abc"},
            {"key": "mol.ads.cmp.tcf.tcstring", "value": _TC_MINIMAL},
        ]
        result = tc_string.find_tc_string_in_storage(items)
        assert result is not None
        assert result == ("mol.ads.cmp.tcf.tcstring", _TC_MINIMAL)

    def test_finds_au_consent_tcf_key(self) -> None:
        """Some CMPs store TC string under au/consent_tcf."""
        items = [{"key": "au/consent_tcf", "value": _TC_MINIMAL}]
        result = tc_string.find_tc_string_in_storage(items)
        assert result is not None
        assert result == ("au/consent_tcf", _TC_MINIMAL)

    def test_returns_none_when_missing(self) -> None:
        items = [{"key": "unrelated_key", "value": "value"}]
        assert tc_string.find_tc_string_in_storage(items) is None

    def test_returns_none_for_empty_list(self) -> None:
        assert tc_string.find_tc_string_in_storage([]) is None

    def test_returns_none_for_empty_value(self) -> None:
        items = [
            {"key": "mol.ads.cmp.tcf.tcstring", "value": ""},
        ]
        assert tc_string.find_tc_string_in_storage(items) is None

    def test_rejects_json_values(self) -> None:
        """JSON blobs should not be treated as TC strings."""
        items = [
            {
                "key": "mol.ads.cmp.tcf.tcstring",
                "value": '{"consent": true}',
            },
        ]
        assert tc_string.find_tc_string_in_storage(items) is None

    def test_rejects_short_values(self) -> None:
        """Values too short to be a TC string should be rejected."""
        items = [
            {"key": "mol.ads.cmp.tcf.tcstring", "value": "CP"},
        ]
        assert tc_string.find_tc_string_in_storage(items) is None

    def test_supports_object_access(self) -> None:
        """Storage item objects with attribute access (StorageItem)."""

        class FakeStorageItem:
            def __init__(self, key: str, value: str) -> None:
                self.key = key
                self.value = value

        items = [
            FakeStorageItem(
                "mol.ads.cmp.tcf.tcstring",
                _TC_MINIMAL,
            ),
        ]
        result = tc_string.find_tc_string_in_storage(items)  # type: ignore[arg-type]
        assert result is not None
        assert result[1] == _TC_MINIMAL


# ====================================================================
# localStorage-based AC String lookup
# ====================================================================


class TestFindAcStringInStorage:
    """Tests for finding AC strings in localStorage items."""

    def test_finds_dmg_media_key(self) -> None:
        """DMG Media CMP stores AC string under mol.ads.cmp.tcf.addtl."""
        items = [
            {"key": "other_key", "value": "abc"},
            {"key": "mol.ads.cmp.tcf.addtl", "value": _AC_SIMPLE},
        ]
        result = tc_string.find_ac_string_in_storage(items)
        assert result is not None
        assert result == ("mol.ads.cmp.tcf.addtl", _AC_SIMPLE)

    def test_returns_none_when_missing(self) -> None:
        items = [{"key": "unrelated_key", "value": "value"}]
        assert tc_string.find_ac_string_in_storage(items) is None

    def test_returns_none_for_empty_list(self) -> None:
        assert tc_string.find_ac_string_in_storage([]) is None

    def test_returns_none_for_empty_value(self) -> None:
        items = [
            {"key": "mol.ads.cmp.tcf.addtl", "value": ""},
        ]
        assert tc_string.find_ac_string_in_storage(items) is None

    def test_rejects_values_without_tilde(self) -> None:
        """AC strings must contain a tilde separator."""
        items = [
            {"key": "mol.ads.cmp.tcf.addtl", "value": "notvalid"},
        ]
        assert tc_string.find_ac_string_in_storage(items) is None

    def test_supports_object_access(self) -> None:
        """Storage item objects with attribute access."""

        class FakeStorageItem:
            def __init__(self, key: str, value: str) -> None:
                self.key = key
                self.value = value

        items = [
            FakeStorageItem("mol.ads.cmp.tcf.addtl", _AC_SIMPLE),
        ]
        result = tc_string.find_ac_string_in_storage(items)  # type: ignore[arg-type]
        assert result is not None
        assert result[1] == _AC_SIMPLE


# ====================================================================
# CMP-aware TC String lookup
# ====================================================================


class TestFindTcStringByProfile:
    """Tests for CMP-profile-aware TC string discovery."""

    def test_finds_tc_in_cookie_by_profile(self) -> None:
        """Profile specifies a cookie name that contains a TC string."""
        cookies = [{"name": "euconsent-v2", "value": _TC_MINIMAL}]
        tc_sources = {"cookies": ["euconsent-v2"]}
        result = tc_string.find_tc_string_by_profile(cookies, [], tc_sources)
        assert result is not None
        assert result == ("euconsent-v2 cookie", _TC_MINIMAL)

    def test_finds_tc_in_storage_by_profile(self) -> None:
        """Profile specifies a localStorage key that contains a TC string."""
        storage = [{"key": "mol.ads.cmp.tcf.tcstring", "value": _TC_MINIMAL}]
        tc_sources = {"storage_keys": ["mol.ads.cmp.tcf.tcstring"]}
        result = tc_string.find_tc_string_by_profile([], storage, tc_sources)
        assert result is not None
        assert result == ("localStorage[mol.ads.cmp.tcf.tcstring]", _TC_MINIMAL)

    def test_returns_none_when_key_absent(self) -> None:
        """No match if the specified key is not in the data."""
        cookies = [{"name": "other", "value": "val"}]
        tc_sources = {"cookies": ["euconsent-v2"]}
        assert tc_string.find_tc_string_by_profile(cookies, [], tc_sources) is None

    def test_returns_none_for_empty_sources(self) -> None:
        """Empty tc_sources dict → no match."""
        cookies = [{"name": "euconsent-v2", "value": _TC_MINIMAL}]
        assert tc_string.find_tc_string_by_profile(cookies, [], {}) is None

    def test_skips_invalid_values(self) -> None:
        """JSON or short values should be rejected even if key matches."""
        cookies = [{"name": "euconsent-v2", "value": '{"json": true}'}]
        tc_sources = {"cookies": ["euconsent-v2"]}
        assert tc_string.find_tc_string_by_profile(cookies, [], tc_sources) is None

    def test_prefers_cookie_over_storage(self) -> None:
        """Cookie match should be returned before checking storage."""
        cookies = [{"name": "euconsent-v2", "value": _TC_MINIMAL}]
        storage = [{"key": "tc_key", "value": _TC_BROAD}]
        tc_sources = {
            "cookies": ["euconsent-v2"],
            "storage_keys": ["tc_key"],
        }
        result = tc_string.find_tc_string_by_profile(cookies, storage, tc_sources)
        assert result is not None
        assert result[0] == "euconsent-v2 cookie"


# ====================================================================
# CMP-aware AC String lookup
# ====================================================================


class TestFindAcStringByProfile:
    """Tests for CMP-profile-aware AC string discovery."""

    def test_finds_ac_in_cookie_by_profile(self) -> None:
        cookies = [{"name": "addtl_consent", "value": _AC_SIMPLE}]
        tc_sources = {"ac_cookies": ["addtl_consent"]}
        result = tc_string.find_ac_string_by_profile(cookies, [], tc_sources)
        assert result is not None
        assert result == ("addtl_consent cookie", _AC_SIMPLE)

    def test_finds_ac_in_storage_by_profile(self) -> None:
        storage = [{"key": "mol.ads.cmp.tcf.addtl", "value": _AC_SIMPLE}]
        tc_sources = {"ac_storage_keys": ["mol.ads.cmp.tcf.addtl"]}
        result = tc_string.find_ac_string_by_profile([], storage, tc_sources)
        assert result is not None
        assert result == ("localStorage[mol.ads.cmp.tcf.addtl]", _AC_SIMPLE)

    def test_returns_none_when_key_absent(self) -> None:
        cookies = [{"name": "other", "value": "val"}]
        tc_sources = {"ac_cookies": ["addtl_consent"]}
        assert tc_string.find_ac_string_by_profile(cookies, [], tc_sources) is None

    def test_returns_none_for_empty_sources(self) -> None:
        assert tc_string.find_ac_string_by_profile([], [], {}) is None


# ====================================================================
# Heuristic TC String scanner
# ====================================================================


class TestScanForTcString:
    """Tests for the brute-force TC string heuristic scanner."""

    def test_finds_tc_in_unknown_cookie(self) -> None:
        """Scanner should decode a valid TC string stored under any name."""
        cookies = [{"name": "mystery_cookie", "value": _TC_MINIMAL}]
        result = tc_string.scan_for_tc_string(cookies, [])
        assert result is not None
        assert result[0] == "mystery_cookie cookie (scanned)"
        assert result[1] == _TC_MINIMAL

    def test_finds_tc_in_unknown_storage_key(self) -> None:
        """Scanner should find TC string in unknown localStorage key."""
        storage = [{"key": "custom_key_42", "value": _TC_MINIMAL}]
        result = tc_string.scan_for_tc_string([], storage)
        assert result is not None
        assert result[0] == "localStorage[custom_key_42] (scanned)"
        assert result[1] == _TC_MINIMAL

    def test_returns_none_when_no_tc_strings(self) -> None:
        """Scanner should not match random values."""
        cookies = [{"name": "session", "value": "abc123"}]
        storage = [{"key": "prefs", "value": '{"dark": true}'}]
        assert tc_string.scan_for_tc_string(cookies, storage) is None

    def test_skips_json_values(self) -> None:
        """JSON blobs should be skipped by the heuristic filter."""
        cookies = [{"name": "data", "value": '{"consent": true}'}]
        assert tc_string.scan_for_tc_string(cookies, []) is None

    def test_skips_short_values(self) -> None:
        """Very short strings cannot be valid TC strings."""
        cookies = [{"name": "c", "value": "CP"}]
        assert tc_string.scan_for_tc_string(cookies, []) is None

    def test_prefers_cookie_over_storage(self) -> None:
        """Cookie match should be returned first."""
        cookies = [{"name": "tc_cookie", "value": _TC_MINIMAL}]
        storage = [{"key": "tc_storage", "value": _TC_BROAD}]
        result = tc_string.scan_for_tc_string(cookies, storage)
        assert result is not None
        assert result[0] == "tc_cookie cookie (scanned)"


# ====================================================================
# Heuristic AC String scanner
# ====================================================================


class TestScanForAcString:
    """Tests for the brute-force AC string heuristic scanner."""

    def test_finds_ac_in_unknown_cookie(self) -> None:
        cookies = [{"name": "weird_ac", "value": _AC_SIMPLE}]
        result = tc_string.scan_for_ac_string(cookies, [])
        assert result is not None
        assert result[0] == "weird_ac cookie (scanned)"
        assert result[1] == _AC_SIMPLE

    def test_finds_ac_in_unknown_storage_key(self) -> None:
        storage = [{"key": "custom_ac", "value": _AC_SIMPLE}]
        result = tc_string.scan_for_ac_string([], storage)
        assert result is not None
        assert result[0] == "localStorage[custom_ac] (scanned)"

    def test_returns_none_when_no_ac_strings(self) -> None:
        cookies = [{"name": "session", "value": "abc123"}]
        assert tc_string.scan_for_ac_string(cookies, []) is None

    def test_skips_non_ac_values(self) -> None:
        """A plain number without tilde should not match."""
        cookies = [{"name": "c", "value": "12345"}]
        assert tc_string.scan_for_ac_string(cookies, []) is None


# ====================================================================
# TC String plausibility validation
# ====================================================================


class TestIsPlausibleTcDecode:
    """Tests for _is_plausible_tc_decode false-positive filtering."""

    def _make_tc_data(self, **overrides: object) -> tc_string.TcStringData:
        """Create a plausible TcStringData with optional overrides."""
        defaults: dict[str, object] = {
            "version": 2,
            "created": "2024-06-15T10:00:00+00:00",
            "last_updated": "2024-06-15T10:00:00+00:00",
            "cmp_id": 68,
            "cmp_version": 1,
            "consent_screen": 0,
            "consent_language": "EN",
            "vendor_list_version": 187,
            "tcf_policy_version": 2,
            "is_service_specific": False,
            "use_non_standard_stacks": False,
            "publisher_country_code": "GB",
            "purpose_consents": [1, 2, 3],
            "purpose_legitimate_interests": [],
            "special_feature_opt_ins": [],
            "vendor_consents": [1, 2],
            "vendor_legitimate_interests": [],
            "raw_string": "fake",
        }
        defaults.update(overrides)
        return tc_string.TcStringData(**defaults)  # type: ignore[arg-type]

    def test_plausible_data_passes(self) -> None:
        """A well-formed TC string should be accepted."""
        data = self._make_tc_data()
        assert tc_string._is_plausible_tc_decode(data) is True

    def test_real_minimal_passes(self) -> None:
        """The _TC_MINIMAL test string should be plausible."""
        decoded = tc_string.decode_tc_string(_TC_MINIMAL)
        assert decoded is not None
        assert tc_string._is_plausible_tc_decode(decoded) is True

    def test_real_broad_passes(self) -> None:
        """The _TC_BROAD test string should be plausible."""
        decoded = tc_string.decode_tc_string(_TC_BROAD)
        assert decoded is not None
        assert tc_string._is_plausible_tc_decode(decoded) is True

    def test_rejects_invalid_consent_language(self) -> None:
        """Non-letter consent language should be rejected."""
        data = self._make_tc_data(consent_language="1Z")
        assert tc_string._is_plausible_tc_decode(data) is False

    def test_rejects_lowercase_consent_language(self) -> None:
        """Lowercase language code should be rejected."""
        data = self._make_tc_data(consent_language="en")
        assert tc_string._is_plausible_tc_decode(data) is False

    def test_rejects_invalid_country_code(self) -> None:
        """Non-letter country code should be rejected."""
        data = self._make_tc_data(publisher_country_code="[B")
        assert tc_string._is_plausible_tc_decode(data) is False

    def test_rejects_empty_country_code(self) -> None:
        data = self._make_tc_data(publisher_country_code="")
        assert tc_string._is_plausible_tc_decode(data) is False

    def test_rejects_high_vendor_list_version(self) -> None:
        """vendorListVersion > 1500 is implausible (current ~290)."""
        data = self._make_tc_data(vendor_list_version=3336)
        assert tc_string._is_plausible_tc_decode(data) is False

    def test_rejects_zero_vendor_list_version(self) -> None:
        data = self._make_tc_data(vendor_list_version=0)
        assert tc_string._is_plausible_tc_decode(data) is False

    def test_rejects_high_tcf_policy_version(self) -> None:
        """tcfPolicyVersion > 10 is implausible."""
        data = self._make_tc_data(tcf_policy_version=42)
        assert tc_string._is_plausible_tc_decode(data) is False

    def test_rejects_zero_tcf_policy_version(self) -> None:
        data = self._make_tc_data(tcf_policy_version=0)
        assert tc_string._is_plausible_tc_decode(data) is False

    def test_rejects_old_timestamp(self) -> None:
        """Dates before 2018 (pre-TCF) should be rejected."""
        data = self._make_tc_data(created="2010-01-01T00:00:00+00:00")
        assert tc_string._is_plausible_tc_decode(data) is False

    def test_rejects_far_future_timestamp(self) -> None:
        """Dates after 2100 should be rejected."""
        data = self._make_tc_data(last_updated="2200-01-01T00:00:00+00:00")
        assert tc_string._is_plausible_tc_decode(data) is False

    def test_rejects_empty_timestamp(self) -> None:
        data = self._make_tc_data(created="")
        assert tc_string._is_plausible_tc_decode(data) is False

    def test_accepts_reasonable_future_timestamp(self) -> None:
        """A timestamp a few years in the future should be accepted."""
        data = self._make_tc_data(created="2053-03-12T00:00:00+00:00")
        assert tc_string._is_plausible_tc_decode(data) is True

    def test_accepts_vendor_list_version_at_boundary(self) -> None:
        """vendorListVersion=1500 (upper limit) should be accepted."""
        data = self._make_tc_data(vendor_list_version=1500)
        assert tc_string._is_plausible_tc_decode(data) is True


# ====================================================================
# Heuristic scanner skip-list
# ====================================================================


class TestHeuristicScanSkipList:
    """Tests for _HEURISTIC_SKIP_COOKIE_NAMES filtering."""

    def test_skips_pid_cookie(self) -> None:
        """pid cookie (Pubmatic etc.) should be skipped."""
        cookies = [{"name": "pid", "value": _TC_MINIMAL}]
        assert tc_string.scan_for_tc_string(cookies, []) is None

    def test_skips_tdcpm_cookie(self) -> None:
        """TDCPM cookie (The Trade Desk) should be skipped."""
        cookies = [{"name": "TDCPM", "value": _TC_MINIMAL}]
        assert tc_string.scan_for_tc_string(cookies, []) is None

    def test_skips_ga_cookie(self) -> None:
        """_ga cookie (Google Analytics) should be skipped."""
        cookies = [{"name": "_ga", "value": _TC_MINIMAL}]
        assert tc_string.scan_for_tc_string(cookies, []) is None

    def test_skips_fbp_cookie(self) -> None:
        """_fbp cookie (Facebook Pixel) should be skipped."""
        cookies = [{"name": "_fbp", "value": _TC_MINIMAL}]
        assert tc_string.scan_for_tc_string(cookies, []) is None

    def test_skips_session_cookie(self) -> None:
        """session cookie should be skipped."""
        cookies = [{"name": "session", "value": _TC_MINIMAL}]
        assert tc_string.scan_for_tc_string(cookies, []) is None

    def test_allows_non_skiplisted_cookie(self) -> None:
        """A cookie not in the skip-list should be scanned."""
        cookies = [{"name": "my_consent_data", "value": _TC_MINIMAL}]
        result = tc_string.scan_for_tc_string(cookies, [])
        assert result is not None
        assert "my_consent_data" in result[0]

    def test_falls_through_to_valid_cookie(self) -> None:
        """Should skip blacklisted cookies and find valid ones."""
        cookies = [
            {"name": "pid", "value": _TC_MINIMAL},
            {"name": "TDCPM", "value": _TC_MINIMAL},
            {"name": "real_consent", "value": _TC_MINIMAL},
        ]
        result = tc_string.scan_for_tc_string(cookies, [])
        assert result is not None
        assert "real_consent" in result[0]

    def test_case_insensitive_skip(self) -> None:
        """Skip-list should match case-insensitively."""
        cookies = [{"name": "PID", "value": _TC_MINIMAL}]
        assert tc_string.scan_for_tc_string(cookies, []) is None


# ====================================================================
# JSON value extraction helpers
# ====================================================================


class TestExtractJsonPath:
    """Tests for _extract_json_path helper."""

    def test_single_level(self) -> None:
        data = {"euconsent": "ABC123"}
        assert tc_string._extract_json_path(data, "euconsent") == "ABC123"

    def test_nested_path(self) -> None:
        data = {"gdpr": {"euconsent": "TC_STRING_VALUE"}}
        assert tc_string._extract_json_path(data, "gdpr.euconsent") == "TC_STRING_VALUE"

    def test_missing_key_returns_none(self) -> None:
        data = {"gdpr": {"other": "val"}}
        assert tc_string._extract_json_path(data, "gdpr.euconsent") is None

    def test_non_string_value_returns_none(self) -> None:
        data = {"gdpr": {"euconsent": 12345}}
        assert tc_string._extract_json_path(data, "gdpr.euconsent") is None

    def test_intermediate_non_dict_returns_none(self) -> None:
        data = {"gdpr": "not_a_dict"}
        assert tc_string._extract_json_path(data, "gdpr.euconsent") is None

    def test_deeply_nested(self) -> None:
        data = {"a": {"b": {"c": "deep_value"}}}
        assert tc_string._extract_json_path(data, "a.b.c") == "deep_value"


# ====================================================================
# JSON field search
# ====================================================================


class TestSearchJsonForField:
    """Tests for _search_json_for_field helper."""

    def test_finds_top_level_field(self) -> None:
        data = {"euconsent": _TC_MINIMAL}
        result = tc_string._search_json_for_field(
            data,
            tc_string._TC_STRING_JSON_FIELDS,
            tc_string._looks_like_tc_string,
        )
        assert result == _TC_MINIMAL

    def test_finds_nested_field(self) -> None:
        data = {"gdpr": {"euconsent": _TC_MINIMAL}}
        result = tc_string._search_json_for_field(
            data,
            tc_string._TC_STRING_JSON_FIELDS,
            tc_string._looks_like_tc_string,
        )
        assert result == _TC_MINIMAL

    def test_returns_none_for_no_match(self) -> None:
        data = {"other_field": "some_value"}
        result = tc_string._search_json_for_field(
            data,
            tc_string._TC_STRING_JSON_FIELDS,
            tc_string._looks_like_tc_string,
        )
        assert result is None

    def test_respects_max_depth(self) -> None:
        data = {"a": {"b": {"c": {"euconsent": _TC_MINIMAL}}}}
        # depth=1 should not reach level 3
        result = tc_string._search_json_for_field(
            data,
            tc_string._TC_STRING_JSON_FIELDS,
            tc_string._looks_like_tc_string,
            max_depth=1,
        )
        assert result is None

    def test_normalises_field_names(self) -> None:
        """Field matching should normalise hyphens and underscores."""
        data = {"euconsent-v2": _TC_MINIMAL}
        result = tc_string._search_json_for_field(
            data,
            tc_string._TC_STRING_JSON_FIELDS,
            tc_string._looks_like_tc_string,
        )
        assert result == _TC_MINIMAL

    def test_rejects_value_failing_validator(self) -> None:
        data = {"euconsent": "short"}
        result = tc_string._search_json_for_field(
            data,
            tc_string._TC_STRING_JSON_FIELDS,
            tc_string._looks_like_tc_string,
        )
        assert result is None


# ====================================================================
# JSON-wrapped TC String extraction (pattern-based, tier 3)
# ====================================================================

# Sourcepoint-style JSON consent value with an embedded TC string.
_SP_CONSENT_JSON = (
    '{"gdpr":{"authId":null,"uuid":"test-uuid","applies":true,"euconsent":"' + _TC_MINIMAL + '","grants":{"vendor1":{"vendorGrant":true}}}}'
)


class TestFindTcStringInJsonStorage:
    """Tests for pattern-based JSON TC string extraction."""

    def test_extracts_tc_from_sourcepoint_consent(self) -> None:
        """Should extract TC string from _sp_user_consent_NNNN JSON."""
        items = [{"key": "_sp_user_consent_7417", "value": _SP_CONSENT_JSON}]
        result = tc_string.find_tc_string_in_json_storage(items)
        assert result is not None
        source, value = result
        assert value == _TC_MINIMAL
        assert "gdpr.euconsent" in source
        assert "_sp_user_consent_7417" in source

    def test_handles_different_property_ids(self) -> None:
        """Property ID varies per site — should match any digits."""
        items = [{"key": "_sp_user_consent_999", "value": _SP_CONSENT_JSON}]
        result = tc_string.find_tc_string_in_json_storage(items)
        assert result is not None

    def test_ignores_non_matching_keys(self) -> None:
        """Keys that don't match the pattern should be skipped."""
        items = [{"key": "some_other_key", "value": _SP_CONSENT_JSON}]
        assert tc_string.find_tc_string_in_json_storage(items) is None

    def test_ignores_non_json_values(self) -> None:
        """Raw string values should be skipped."""
        items = [{"key": "_sp_user_consent_7417", "value": _TC_MINIMAL}]
        assert tc_string.find_tc_string_in_json_storage(items) is None

    def test_ignores_invalid_json(self) -> None:
        """Malformed JSON should be skipped gracefully."""
        items = [{"key": "_sp_user_consent_7417", "value": "{invalid json"}]
        assert tc_string.find_tc_string_in_json_storage(items) is None

    def test_ignores_json_without_tc_string(self) -> None:
        """JSON without the expected TC string field should return None."""
        items = [{"key": "_sp_user_consent_7417", "value": '{"gdpr": {"other": "val"}}'}]
        assert tc_string.find_tc_string_in_json_storage(items) is None

    def test_empty_storage(self) -> None:
        assert tc_string.find_tc_string_in_json_storage([]) is None

    def test_ignores_key_without_numeric_suffix(self) -> None:
        """_sp_user_consent_ without digits should not match."""
        items = [{"key": "_sp_user_consent_abc", "value": _SP_CONSENT_JSON}]
        assert tc_string.find_tc_string_in_json_storage(items) is None


class TestFindAcStringInJsonStorage:
    """Tests for pattern-based JSON AC string extraction."""

    def test_returns_none_when_no_ac_patterns(self) -> None:
        """Current patterns have no AC paths — should return None."""
        items = [{"key": "_sp_user_consent_7417", "value": _SP_CONSENT_JSON}]
        assert tc_string.find_ac_string_in_json_storage(items) is None

    def test_empty_storage(self) -> None:
        assert tc_string.find_ac_string_in_json_storage([]) is None


# ====================================================================
# CMP profile with storage_key_patterns (tier 2 extension)
# ====================================================================


class TestProfileStorageKeyPatterns:
    """Tests for CMP profile regex+JSON path patterns in tier 2."""

    def test_finds_tc_via_storage_key_pattern(self) -> None:
        """Profile with storage_key_patterns should extract TC from JSON."""
        items = [{"key": "_sp_user_consent_7417", "value": _SP_CONSENT_JSON}]
        tc_sources = {
            "cookies": ["euconsent-v2"],
            "storage_key_patterns": [
                {
                    "pattern": r"^_sp_user_consent_\d+$",
                    "tc_path": "gdpr.euconsent",
                }
            ],
        }
        result = tc_string.find_tc_string_by_profile([], items, tc_sources)
        assert result is not None
        assert result[1] == _TC_MINIMAL
        assert "gdpr.euconsent" in result[0]

    def test_cookie_takes_priority_over_pattern(self) -> None:
        """Cookie match should be preferred over storage_key_patterns."""
        cookies = [{"name": "euconsent-v2", "value": _TC_BROAD}]
        items = [{"key": "_sp_user_consent_7417", "value": _SP_CONSENT_JSON}]
        tc_sources = {
            "cookies": ["euconsent-v2"],
            "storage_key_patterns": [
                {
                    "pattern": r"^_sp_user_consent_\d+$",
                    "tc_path": "gdpr.euconsent",
                }
            ],
        }
        result = tc_string.find_tc_string_by_profile(cookies, items, tc_sources)
        assert result is not None
        assert result[0] == "euconsent-v2 cookie"
        assert result[1] == _TC_BROAD

    def test_no_match_when_pattern_doesnt_match(self) -> None:
        """Should return None when key doesn't match the regex."""
        items = [{"key": "other_key", "value": _SP_CONSENT_JSON}]
        tc_sources = {
            "storage_key_patterns": [
                {
                    "pattern": r"^_sp_user_consent_\d+$",
                    "tc_path": "gdpr.euconsent",
                }
            ],
        }
        assert tc_string.find_tc_string_by_profile([], items, tc_sources) is None

    def test_ac_storage_key_patterns(self) -> None:
        """AC patterns should work the same way as TC patterns."""
        ac_json = '{"gdpr": {"addtlConsent": "' + _AC_SIMPLE + '"}}'
        items = [{"key": "_sp_user_consent_7417", "value": ac_json}]
        tc_sources = {
            "ac_storage_key_patterns": [
                {
                    "pattern": r"^_sp_user_consent_\d+$",
                    "ac_path": "gdpr.addtlConsent",
                }
            ],
        }
        result = tc_string.find_ac_string_by_profile([], items, tc_sources)
        assert result is not None
        assert result[1] == _AC_SIMPLE


# ====================================================================
# JSON heuristic scan (tier 5)
# ====================================================================


class TestScanJsonForTcString:
    """Tests for the JSON heuristic TC string scanner."""

    def test_finds_tc_in_nested_json(self) -> None:
        """Should find a TC string inside a JSON value."""
        items = [
            {"key": "unknown_consent_data", "value": '{"euconsent": "' + _TC_MINIMAL + '"}'},
        ]
        result = tc_string.scan_json_for_tc_string(items)
        assert result is not None
        assert result[1] == _TC_MINIMAL
        assert "unknown_consent_data" in result[0]

    def test_finds_tc_deeply_nested(self) -> None:
        """Should find TC string nested 2 levels deep."""
        items = [
            {
                "key": "consent",
                "value": '{"data": {"tcString": "' + _TC_MINIMAL + '"}}',
            },
        ]
        result = tc_string.scan_json_for_tc_string(items)
        assert result is not None
        assert result[1] == _TC_MINIMAL

    def test_skips_non_json_values(self) -> None:
        """Raw string values should be ignored."""
        items = [{"key": "consent", "value": _TC_MINIMAL}]
        assert tc_string.scan_json_for_tc_string(items) is None

    def test_rejects_implausible_decode(self) -> None:
        """Values that parse as TC String but are implausible should be rejected."""
        # Use a very short dummy value that won't decode validly
        items = [
            {"key": "data", "value": '{"euconsent": "AAAAAAAAAA"}'},
        ]
        result = tc_string.scan_json_for_tc_string(items)
        assert result is None

    def test_empty_storage(self) -> None:
        assert tc_string.scan_json_for_tc_string([]) is None

    def test_invalid_json_skipped(self) -> None:
        items = [{"key": "data", "value": "{not json at all"}]
        assert tc_string.scan_json_for_tc_string(items) is None


class TestScanJsonForAcString:
    """Tests for the JSON heuristic AC string scanner."""

    def test_finds_ac_in_json(self) -> None:
        items = [
            {"key": "consent", "value": '{"addtlConsent": "' + _AC_SIMPLE + '"}'},
        ]
        result = tc_string.scan_json_for_ac_string(items)
        assert result is not None
        assert result[1] == _AC_SIMPLE

    def test_finds_ac_nested(self) -> None:
        items = [
            {
                "key": "consent",
                "value": '{"data": {"addtl_consent": "' + _AC_SIMPLE + '"}}',
            },
        ]
        result = tc_string.scan_json_for_ac_string(items)
        assert result is not None

    def test_empty_storage(self) -> None:
        assert tc_string.scan_json_for_ac_string([]) is None

    def test_skips_non_json(self) -> None:
        items = [{"key": "data", "value": _AC_SIMPLE}]
        assert tc_string.scan_json_for_ac_string(items) is None
