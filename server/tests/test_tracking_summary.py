"""Tests for src.analysis.tracking_summary — summary builders."""

from __future__ import annotations

from unittest import mock

from src.analysis.tracking_summary import (
    _build_domain_breakdown,
    _build_storage_preview,
    _get_third_party_domains,
    _group_by_domain,
    build_pre_consent_stats,
    build_tracking_summary,
)
from src.models import analysis, tracking_data

# ── helpers ─────────────────────────────────────────────────────


def _cookie(name: str, domain: str) -> tracking_data.TrackedCookie:
    return tracking_data.TrackedCookie(
        name=name,
        value="v",
        domain=domain,
        path="/",
        expires=0,
        http_only=False,
        secure=False,
        same_site="None",
        timestamp="t",
    )


def _script(url: str, domain: str) -> tracking_data.TrackedScript:
    return tracking_data.TrackedScript(url=url, domain=domain, timestamp="t")


def _request(url: str, domain: str, *, third_party: bool = False) -> tracking_data.NetworkRequest:
    return tracking_data.NetworkRequest(
        url=url,
        domain=domain,
        method="GET",
        resource_type="xhr",
        is_third_party=third_party,
        timestamp="t",
    )


def _storage(key: str) -> tracking_data.StorageItem:
    return tracking_data.StorageItem(key=key, value="v" * 200, timestamp="t")


# ── _group_by_domain ───────────────────────────────────────────


class TestGroupByDomain:
    def test_empty(self) -> None:
        result = _group_by_domain([], [], [])
        assert result == {}

    def test_groups_cookies_scripts_requests(self) -> None:
        cookies = [_cookie("a", "example.com"), _cookie("b", "tracker.com")]
        scripts = [_script("https://example.com/app.js", "example.com")]
        requests = [_request("https://tracker.com/pixel", "tracker.com")]
        result = _group_by_domain(cookies, scripts, requests)
        assert set(result.keys()) == {"example.com", "tracker.com"}
        assert len(result["example.com"].cookies) == 1
        assert len(result["example.com"].scripts) == 1
        assert len(result["tracker.com"].cookies) == 1
        assert len(result["tracker.com"].network_requests) == 1


# ── _get_third_party_domains ──────────────────────────────────


class TestGetThirdPartyDomains:
    def test_no_third_party(self) -> None:
        dd: dict[str, analysis.DomainData] = {"example.com": analysis.DomainData()}
        assert _get_third_party_domains(dd, "https://example.com") == []

    def test_identifies_third_party(self) -> None:
        dd: dict[str, analysis.DomainData] = {
            "example.com": analysis.DomainData(),
            "tracker.com": analysis.DomainData(),
        }
        result = _get_third_party_domains(dd, "https://example.com")
        assert result == ["tracker.com"]

    def test_subdomain_is_first_party(self) -> None:
        dd: dict[str, analysis.DomainData] = {
            "cdn.example.com": analysis.DomainData(),
        }
        result = _get_third_party_domains(dd, "https://example.com")
        assert result == []


# ── _build_domain_breakdown ───────────────────────────────────


class TestBuildDomainBreakdown:
    def test_structure(self) -> None:
        dd: dict[str, analysis.DomainData] = {
            "example.com": analysis.DomainData(
                cookies=[_cookie("a", "example.com")],
                scripts=[_script("https://example.com/app.js", "example.com")],
                network_requests=[
                    _request("https://example.com/api", "example.com"),
                ],
            ),
        }
        result = _build_domain_breakdown(dd)
        assert len(result) == 1
        bd = result[0]
        assert bd.domain == "example.com"
        assert bd.cookie_count == 1
        assert bd.cookie_names == ["a"]
        assert bd.script_count == 1
        assert bd.request_count == 1
        assert bd.request_types == ["xhr"]


# ── _build_storage_preview ────────────────────────────────────


class TestBuildStoragePreview:
    def test_truncates_value(self) -> None:
        items = [_storage("key")]
        preview = _build_storage_preview(items)
        assert len(preview) == 1
        assert preview[0]["key"] == "key"
        assert len(preview[0]["valuePreview"]) == 100

    def test_empty(self) -> None:
        assert _build_storage_preview([]) == []


# ── build_tracking_summary ────────────────────────────────────


class TestBuildTrackingSummary:
    def test_basic_summary(self) -> None:
        cookies = [_cookie("a", "example.com"), _cookie("b", "tracker.com")]
        scripts = [_script("https://example.com/app.js", "example.com")]
        requests = [_request("https://tracker.com/pixel", "tracker.com")]
        local = [_storage("ls1")]
        session = [_storage("ss1")]

        result = build_tracking_summary(
            cookies,
            scripts,
            requests,
            local,
            session,
            analyzed_url="https://example.com",
        )
        assert isinstance(result, analysis.TrackingSummary)
        assert result.analyzed_url == "https://example.com"
        assert result.total_cookies == 2
        assert result.total_scripts == 1
        assert result.total_network_requests == 1
        assert result.local_storage_items == 1
        assert result.session_storage_items == 1
        assert "tracker.com" in result.third_party_domains

    def test_empty_data(self) -> None:
        result = build_tracking_summary([], [], [], [], [], analyzed_url="https://example.com")
        assert result.total_cookies == 0
        assert result.third_party_domains == []
        assert result.domain_breakdown == []


# ── build_pre_consent_stats ──────────────────────────────────


class TestBuildPreConsentStats:
    def test_counts_tracking_cookies(self) -> None:
        cookies = [
            _cookie("_ga", "example.com"),
            _cookie("session_id", "example.com"),
        ]
        with mock.patch("src.analysis.tracking_summary.loader.get_tracking_scripts", return_value=[]):
            result = build_pre_consent_stats(
                cookies,
                [],
                [],
                {"local_storage": [], "session_storage": []},
            )
        assert result.total_cookies == 2
        assert result.tracking_cookies == 1  # _ga matches

    def test_counts_tracker_requests(self) -> None:
        reqs = [
            _request("https://doubleclick.net/pixel", "doubleclick.net", third_party=True),
            _request("https://example.com/api", "example.com"),
        ]
        with mock.patch("src.analysis.tracking_summary.loader.get_tracking_scripts", return_value=[]):
            result = build_pre_consent_stats(
                [],
                [],
                reqs,
                {"local_storage": [], "session_storage": []},
            )
        assert result.tracker_requests == 1

    def test_storage_totals(self) -> None:
        with mock.patch("src.analysis.tracking_summary.loader.get_tracking_scripts", return_value=[]):
            result = build_pre_consent_stats(
                [],
                [],
                [],
                {"local_storage": [_storage("a"), _storage("b")], "session_storage": [_storage("c")]},
            )
        assert result.total_local_storage == 2
        assert result.total_session_storage == 1
