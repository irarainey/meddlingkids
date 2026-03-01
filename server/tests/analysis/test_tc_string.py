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
