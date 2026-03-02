"""Tests for privacy-relevant cookie decoders."""

from __future__ import annotations

import pytest

from src.analysis import cookie_decoders

# ====================================================================
# USP String
# ====================================================================


class TestDecodeUspString:
    """Tests for IAB US Privacy String (CCPA) decoding."""

    def test_basic_usp(self) -> None:
        result = cookie_decoders.decode_usp_string("1YNN")
        assert result is not None
        assert result["version"] == 1
        assert result["noticeGiven"] is True
        assert result["optedOut"] is False
        assert result["lspaCovered"] is False

    def test_opted_out(self) -> None:
        result = cookie_decoders.decode_usp_string("1NYN")
        assert result is not None
        assert result["noticeGiven"] is False
        assert result["optedOut"] is True

    def test_all_dashes(self) -> None:
        result = cookie_decoders.decode_usp_string("1---")
        assert result is not None
        assert result["noticeGiven"] is False
        assert result["optedOut"] is False
        assert result["lspaCovered"] is False
        assert result["noticeLabel"] == "Not applicable"
        assert result["optOutLabel"] == "Not applicable"
        assert result["lspaLabel"] == "Not applicable"

    def test_labels(self) -> None:
        result = cookie_decoders.decode_usp_string("1YYY")
        assert result is not None
        assert result["noticeLabel"] == "Yes"
        assert result["optOutLabel"] == "Yes"
        assert result["lspaLabel"] == "Yes"

    def test_raw_preserved(self) -> None:
        result = cookie_decoders.decode_usp_string("1YNN")
        assert result is not None
        assert result["rawString"] == "1YNN"

    def test_lowercase_normalised(self) -> None:
        result = cookie_decoders.decode_usp_string("1ynn")
        assert result is not None
        assert result["noticeGiven"] is True
        assert result["optedOut"] is False

    def test_empty_returns_none(self) -> None:
        assert cookie_decoders.decode_usp_string("") is None

    def test_short_returns_none(self) -> None:
        assert cookie_decoders.decode_usp_string("1Y") is None

    def test_invalid_version_returns_none(self) -> None:
        assert cookie_decoders.decode_usp_string("XYNN") is None


class TestFindUspInCookies:
    """Tests for finding USP string in cookies."""

    def test_finds_usprivacy(self) -> None:
        cookies = [
            {"name": "other", "value": "abc"},
            {"name": "usprivacy", "value": "1YNN"},
        ]
        result = cookie_decoders.find_usp_in_cookies(cookies)
        assert result is not None
        assert result["version"] == 1

    def test_returns_none_when_missing(self) -> None:
        cookies = [{"name": "other", "value": "abc"}]
        assert cookie_decoders.find_usp_in_cookies(cookies) is None

    def test_returns_none_for_empty_value(self) -> None:
        cookies = [{"name": "usprivacy", "value": ""}]
        assert cookie_decoders.find_usp_in_cookies(cookies) is None

    def test_returns_none_for_empty_list(self) -> None:
        assert cookie_decoders.find_usp_in_cookies([]) is None


# ====================================================================
# GPP String
# ====================================================================


class TestDecodeGppString:
    """Tests for IAB GPP String decoding."""

    def test_basic_gpp(self) -> None:
        result = cookie_decoders.decode_gpp_string(
            "DBABMA~CPXxRfAPXxRfAAfKABENB-CgAAAAAAAAAAYgAAAAAAAA",
            "2",
        )
        assert result is not None
        assert result["segmentCount"] == 2
        assert result["sectionIds"] == [2]
        assert len(result["sections"]) == 1  # type: ignore[arg-type]
        assert result["sections"][0]["name"] == "TCF EU v2"  # type: ignore[index]

    def test_multiple_section_ids(self) -> None:
        result = cookie_decoders.decode_gpp_string(
            "HEADER~SEG1~SEG2",
            "2,6,7",
        )
        assert result is not None
        assert result["sectionIds"] == [2, 6, 7]
        sections = result["sections"]
        assert len(sections) == 3  # type: ignore[arg-type, attr-defined]

    def test_section_names(self) -> None:
        result = cookie_decoders.decode_gpp_string("X", "6,8")
        assert result is not None
        names = [s["name"] for s in result["sections"]]  # type: ignore[union-attr, attr-defined]
        assert "USP v1 (CCPA)" in names
        assert "US California (CPRA)" in names

    def test_no_sid(self) -> None:
        result = cookie_decoders.decode_gpp_string("HEADER~SEG", None)
        assert result is not None
        assert result["sectionIds"] == []
        assert result["segmentCount"] == 2

    def test_raw_preserved(self) -> None:
        raw = "DBABMA~CPXxRfAPXxRfAAfKABENB-CgAAAAAAAAAAYgAAAAAAAA"
        result = cookie_decoders.decode_gpp_string(raw)
        assert result is not None
        assert result["rawString"] == raw

    def test_empty_returns_none(self) -> None:
        assert cookie_decoders.decode_gpp_string("") is None

    def test_underscore_separated_sids(self) -> None:
        result = cookie_decoders.decode_gpp_string("X", "2_6_7")
        assert result is not None
        assert result["sectionIds"] == [2, 6, 7]


class TestFindGppInCookies:
    """Tests for finding GPP string in cookies."""

    def test_finds_gpp_with_sid(self) -> None:
        cookies = [
            {"name": "__gpp", "value": "HEADER~SEG"},
            {"name": "__gpp_sid", "value": "2,6"},
        ]
        result = cookie_decoders.find_gpp_in_cookies(cookies)
        assert result is not None
        assert result["sectionIds"] == [2, 6]

    def test_finds_gpp_without_sid(self) -> None:
        cookies = [{"name": "__gpp", "value": "HEADER~SEG"}]
        result = cookie_decoders.find_gpp_in_cookies(cookies)
        assert result is not None
        assert result["sectionIds"] == []

    def test_returns_none_when_missing(self) -> None:
        cookies = [{"name": "other", "value": "abc"}]
        assert cookie_decoders.find_gpp_in_cookies(cookies) is None


# ====================================================================
# Google Analytics (_ga)
# ====================================================================


class TestDecodeGaCookie:
    """Tests for Google Analytics _ga cookie decoding."""

    def test_basic_ga(self) -> None:
        result = cookie_decoders.decode_ga_cookie(
            "GA1.2.123456789.1234567890",
        )
        assert result is not None
        assert result["clientId"] == "123456789"
        assert result["firstVisitTimestamp"] == 1234567890
        assert result["firstVisit"] is not None
        assert "2009-02-13" in result["firstVisit"]  # type: ignore[operator]

    def test_raw_preserved(self) -> None:
        raw = "GA1.2.123456789.1234567890"
        result = cookie_decoders.decode_ga_cookie(raw)
        assert result is not None
        assert result["rawValue"] == raw

    def test_ga4_format(self) -> None:
        result = cookie_decoders.decode_ga_cookie(
            "GA1.1.987654321.1700000000",
        )
        assert result is not None
        assert result["clientId"] == "987654321"
        assert result["firstVisitTimestamp"] == 1700000000

    def test_empty_returns_none(self) -> None:
        assert cookie_decoders.decode_ga_cookie("") is None

    def test_no_match_returns_none(self) -> None:
        assert cookie_decoders.decode_ga_cookie("random_value") is None

    def test_too_few_parts_returns_none(self) -> None:
        assert cookie_decoders.decode_ga_cookie("GA1.2") is None


class TestFindGaInCookies:
    """Tests for finding _ga cookie in cookie list."""

    def test_finds_ga(self) -> None:
        cookies = [
            {"name": "_ga", "value": "GA1.2.123456789.1234567890"},
        ]
        result = cookie_decoders.find_ga_in_cookies(cookies)
        assert result is not None
        assert result["clientId"] == "123456789"

    def test_returns_none_when_missing(self) -> None:
        cookies = [{"name": "other", "value": "abc"}]
        assert cookie_decoders.find_ga_in_cookies(cookies) is None


# ====================================================================
# Facebook _fbp / _fbc
# ====================================================================


class TestDecodeFbpCookie:
    """Tests for Facebook _fbp browser ID cookie."""

    def test_basic_fbp(self) -> None:
        result = cookie_decoders.decode_fbp_cookie(
            "fb.1.1700000000000.ABC123DEF",
        )
        assert result is not None
        assert result["browserId"] == "ABC123DEF"
        assert result["createdTimestamp"] == 1700000000000
        assert result["created"] is not None
        assert "2023-11-14" in result["created"]  # type: ignore[operator]

    def test_empty_returns_none(self) -> None:
        assert cookie_decoders.decode_fbp_cookie("") is None

    def test_no_match_returns_none(self) -> None:
        assert cookie_decoders.decode_fbp_cookie("random") is None


class TestDecodeFbcCookie:
    """Tests for Facebook _fbc click ID cookie."""

    def test_basic_fbc(self) -> None:
        result = cookie_decoders.decode_fbc_cookie(
            "fb.1.1700000000000.AbCdEfGhIjKlMnOp",
        )
        assert result is not None
        assert result["fbclid"] == "AbCdEfGhIjKlMnOp"
        assert result["clickTimestamp"] == 1700000000000

    def test_empty_returns_none(self) -> None:
        assert cookie_decoders.decode_fbc_cookie("") is None


class TestFindFbInCookies:
    """Tests for finding Facebook cookies."""

    def test_finds_fbp_only(self) -> None:
        cookies = [
            {"name": "_fbp", "value": "fb.1.1700000000000.BROWSER"},
        ]
        result = cookie_decoders.find_fb_in_cookies(cookies)
        assert result is not None
        assert "fbp" in result
        assert "fbc" not in result

    def test_finds_both(self) -> None:
        cookies = [
            {"name": "_fbp", "value": "fb.1.1700000000000.BROWSER"},
            {"name": "_fbc", "value": "fb.1.1700000000000.CLICK"},
        ]
        result = cookie_decoders.find_fb_in_cookies(cookies)
        assert result is not None
        assert "fbp" in result
        assert "fbc" in result

    def test_returns_none_when_missing(self) -> None:
        cookies = [{"name": "other", "value": "abc"}]
        assert cookie_decoders.find_fb_in_cookies(cookies) is None


# ====================================================================
# Google Ads _gcl_au / _gcl_aw
# ====================================================================


class TestDecodeGclAuCookie:
    """Tests for Google Ads _gcl_au cookie."""

    def test_basic_gcl_au(self) -> None:
        result = cookie_decoders.decode_gcl_au_cookie("1.1.1700000000")
        assert result is not None
        assert result["version"] == "1"
        assert result["createdTimestamp"] == 1700000000

    def test_empty_returns_none(self) -> None:
        assert cookie_decoders.decode_gcl_au_cookie("") is None

    def test_too_few_parts_returns_none(self) -> None:
        assert cookie_decoders.decode_gcl_au_cookie("1.2") is None


class TestDecodeGclAwCookie:
    """Tests for Google Ads _gcl_aw cookie."""

    def test_basic_gcl_aw(self) -> None:
        result = cookie_decoders.decode_gcl_aw_cookie(
            "GCL.1700000000.EAIaIQobChMI",
        )
        assert result is not None
        assert result["gclid"] == "EAIaIQobChMI"
        assert result["clickTimestamp"] == 1700000000

    def test_empty_returns_none(self) -> None:
        assert cookie_decoders.decode_gcl_aw_cookie("") is None

    def test_too_few_parts_returns_none(self) -> None:
        assert cookie_decoders.decode_gcl_aw_cookie("GCL.123") is None


class TestFindGclInCookies:
    """Tests for finding Google Ads cookies."""

    def test_finds_gcl_au_only(self) -> None:
        cookies = [
            {"name": "_gcl_au", "value": "1.1.1700000000"},
        ]
        result = cookie_decoders.find_gcl_in_cookies(cookies)
        assert result is not None
        assert "gclAu" in result
        assert "gclAw" not in result

    def test_finds_both(self) -> None:
        cookies = [
            {"name": "_gcl_au", "value": "1.1.1700000000"},
            {"name": "_gcl_aw", "value": "GCL.1700000000.GCLID"},
        ]
        result = cookie_decoders.find_gcl_in_cookies(cookies)
        assert result is not None
        assert "gclAu" in result
        assert "gclAw" in result

    def test_returns_none_when_missing(self) -> None:
        cookies = [{"name": "other", "value": "abc"}]
        assert cookie_decoders.find_gcl_in_cookies(cookies) is None


# ====================================================================
# OneTrust (OptanonConsent)
# ====================================================================


class TestDecodeOptanonConsent:
    """Tests for OneTrust OptanonConsent cookie."""

    def test_basic_optanon(self) -> None:
        raw = "isGpcApplied=false&datestamp=Mon+Jan+01+2024&groups=C0001%3A1%2CC0002%3A0%2CC0003%3A0%2CC0004%3A1&consentId=abc-123"
        result = cookie_decoders.decode_optanon_consent(raw)
        assert result is not None
        cats = result["categories"]
        assert len(cats) == 4  # type: ignore[arg-type]
        # Strictly Necessary = consented
        assert cats[0]["name"] == "Strictly Necessary"  # type: ignore[index]
        assert cats[0]["consented"] is True  # type: ignore[index]
        # Performance = not consented
        assert cats[1]["name"] == "Performance / Analytics"  # type: ignore[index]
        assert cats[1]["consented"] is False  # type: ignore[index]
        # Targeting = consented
        assert cats[3]["consented"] is True  # type: ignore[index]

    def test_gpc_applied(self) -> None:
        raw = "isGpcApplied=true&groups=C0001%3A1"
        result = cookie_decoders.decode_optanon_consent(raw)
        assert result is not None
        assert result["isGpcApplied"] is True

    def test_consent_id(self) -> None:
        raw = "consentId=uuid-here&groups=C0001%3A1"
        result = cookie_decoders.decode_optanon_consent(raw)
        assert result is not None
        assert result["consentId"] == "uuid-here"

    def test_empty_returns_none(self) -> None:
        assert cookie_decoders.decode_optanon_consent("") is None


class TestFindOptanonInCookies:
    """Tests for finding OptanonConsent cookie."""

    def test_finds_optanon(self) -> None:
        cookies = [
            {
                "name": "OptanonConsent",
                "value": "groups=C0001%3A1%2CC0002%3A0",
            },
        ]
        result = cookie_decoders.find_optanon_in_cookies(cookies)
        assert result is not None
        assert len(result["categories"]) == 2  # type: ignore[arg-type]

    def test_returns_none_when_missing(self) -> None:
        cookies = [{"name": "other", "value": "abc"}]
        assert cookie_decoders.find_optanon_in_cookies(cookies) is None


# ====================================================================
# Cookiebot (CookieConsent)
# ====================================================================


class TestDecodeCookiebotConsent:
    """Tests for Cookiebot CookieConsent cookie."""

    def test_json_format(self) -> None:
        raw = '{"stamp":"abc","necessary":true,"preferences":false,"statistics":false,"marketing":true,"utc":"2024-01-01"}'
        result = cookie_decoders.decode_cookiebot_consent(raw)
        assert result is not None
        cats = result["categories"]
        assert len(cats) == 4  # type: ignore[arg-type]
        assert cats[0]["name"] == "Necessary"  # type: ignore[index]
        assert cats[0]["consented"] is True  # type: ignore[index]
        assert cats[3]["name"] == "Marketing"  # type: ignore[index]
        assert cats[3]["consented"] is True  # type: ignore[index]

    def test_stamp_format(self) -> None:
        raw = "stamp:'hash123',necessary:true,preferences:false,statistics:true,marketing:false"
        result = cookie_decoders.decode_cookiebot_consent(raw)
        assert result is not None
        cats = result["categories"]
        assert len(cats) == 4  # type: ignore[arg-type]
        assert cats[0]["consented"] is True  # type: ignore[index]
        assert cats[1]["consented"] is False  # type: ignore[index]
        assert cats[2]["consented"] is True  # type: ignore[index]
        assert cats[3]["consented"] is False  # type: ignore[index]

    def test_empty_returns_none(self) -> None:
        assert cookie_decoders.decode_cookiebot_consent("") is None

    def test_random_string_returns_none(self) -> None:
        assert cookie_decoders.decode_cookiebot_consent("random") is None


class TestFindCookiebotInCookies:
    """Tests for finding CookieConsent cookie."""

    def test_finds_cookiebot(self) -> None:
        raw = '{"necessary":true,"preferences":false,"statistics":false,"marketing":false}'
        cookies = [{"name": "CookieConsent", "value": raw}]
        result = cookie_decoders.find_cookiebot_in_cookies(cookies)
        assert result is not None
        assert len(result["categories"]) == 4  # type: ignore[arg-type]

    def test_returns_none_when_missing(self) -> None:
        cookies = [{"name": "other", "value": "abc"}]
        assert cookie_decoders.find_cookiebot_in_cookies(cookies) is None


# ====================================================================
# Google SOCS
# ====================================================================


class TestDecodeSocsCookie:
    """Tests for Google SOCS consent cookie."""

    def test_customised_mode(self) -> None:
        """Base64 of 'C...' → All accepted."""
        import base64

        raw = base64.b64encode(b"Ctest").decode()
        result = cookie_decoders.decode_socs_cookie(raw)
        assert result is not None
        assert result["modeChar"] == "C"
        assert "accepted" in result["consentMode"].lower()  # type: ignore[attr-defined]

    def test_rejected_mode(self) -> None:
        import base64

        raw = base64.b64encode(b"Atest").decode()
        result = cookie_decoders.decode_socs_cookie(raw)
        assert result is not None
        assert result["modeChar"] == "A"
        assert "rejected" in result["consentMode"].lower()  # type: ignore[attr-defined]

    def test_essential_mode(self) -> None:
        import base64

        raw = base64.b64encode(b"Etest").decode()
        result = cookie_decoders.decode_socs_cookie(raw)
        assert result is not None
        assert result["modeChar"] == "E"
        assert "essential" in result["consentMode"].lower()  # type: ignore[attr-defined]

    def test_empty_returns_none(self) -> None:
        assert cookie_decoders.decode_socs_cookie("") is None


class TestFindSocsInCookies:
    """Tests for finding SOCS cookie."""

    def test_finds_socs(self) -> None:
        import base64

        raw = base64.b64encode(b"Cexample").decode()
        cookies = [{"name": "SOCS", "value": raw}]
        result = cookie_decoders.find_socs_in_cookies(cookies)
        assert result is not None
        assert result["modeChar"] == "C"

    def test_returns_none_when_missing(self) -> None:
        cookies = [{"name": "other", "value": "abc"}]
        assert cookie_decoders.find_socs_in_cookies(cookies) is None


# ====================================================================
# GPC / DNT
# ====================================================================


class TestDetectGpcDnt:
    """Tests for Global Privacy Control and Do Not Track detection."""

    def test_gpc_enabled(self) -> None:
        result = cookie_decoders.detect_gpc_dnt(
            [],
            response_headers={"Sec-GPC": "1"},
        )
        assert result is not None
        assert result["gpcEnabled"] is True
        assert result["dntEnabled"] is False

    def test_dnt_enabled(self) -> None:
        result = cookie_decoders.detect_gpc_dnt(
            [],
            response_headers={"DNT": "1"},
        )
        assert result is not None
        assert result["gpcEnabled"] is False
        assert result["dntEnabled"] is True

    def test_both_enabled(self) -> None:
        result = cookie_decoders.detect_gpc_dnt(
            [],
            response_headers={"Sec-GPC": "1", "DNT": "1"},
        )
        assert result is not None
        assert result["gpcEnabled"] is True
        assert result["dntEnabled"] is True

    def test_none_when_absent(self) -> None:
        result = cookie_decoders.detect_gpc_dnt(
            [],
            response_headers={},
        )
        assert result is None

    def test_none_without_headers(self) -> None:
        result = cookie_decoders.detect_gpc_dnt([])
        assert result is None


# ====================================================================
# Master decoder
# ====================================================================


class TestDecodeAllPrivacyCookies:
    """Tests for the combined decode_all_privacy_cookies helper."""

    def test_empty_cookies(self) -> None:
        result = cookie_decoders.decode_all_privacy_cookies([])
        assert result == {}

    def test_usp_and_ga(self) -> None:
        cookies = [
            {"name": "usprivacy", "value": "1YNN"},
            {"name": "_ga", "value": "GA1.2.111.222"},
        ]
        result = cookie_decoders.decode_all_privacy_cookies(cookies)
        assert "uspString" in result
        assert "googleAnalytics" in result
        assert "gppString" not in result

    def test_all_known_cookies(self) -> None:
        import base64

        cookies = [
            {"name": "usprivacy", "value": "1YNN"},
            {"name": "__gpp", "value": "HEADER~SEG"},
            {"name": "__gpp_sid", "value": "2"},
            {"name": "_ga", "value": "GA1.2.111.222"},
            {"name": "_fbp", "value": "fb.1.1700000000000.BROWSER"},
            {"name": "_gcl_au", "value": "1.1.1700000000"},
            {"name": "OptanonConsent", "value": "groups=C0001%3A1"},
            {
                "name": "CookieConsent",
                "value": '{"necessary":true,"preferences":false,"statistics":false,"marketing":false}',
            },
            {
                "name": "SOCS",
                "value": base64.b64encode(b"Cexample").decode(),
            },
        ]
        result = cookie_decoders.decode_all_privacy_cookies(cookies)
        assert "uspString" in result
        assert "gppString" in result
        assert "googleAnalytics" in result
        assert "facebookPixel" in result
        assert "googleAds" in result
        assert "oneTrust" in result
        assert "cookiebot" in result
        assert "googleSocs" in result

    @pytest.mark.parametrize(
        ("cookie_name", "cookie_value", "expected_key"),
        [
            ("usprivacy", "1YNN", "uspString"),
            ("__gpp", "HEADER", "gppString"),
            ("_ga", "GA1.2.111.222", "googleAnalytics"),
            ("_fbp", "fb.1.1000.ID", "facebookPixel"),
            ("_gcl_au", "1.1.1700000000", "googleAds"),
            ("OptanonConsent", "groups=C0001%3A1", "oneTrust"),
        ],
    )
    def test_individual_cookie_detected(
        self,
        cookie_name: str,
        cookie_value: str,
        expected_key: str,
    ) -> None:
        cookies = [{"name": cookie_name, "value": cookie_value}]
        result = cookie_decoders.decode_all_privacy_cookies(cookies)
        assert expected_key in result
