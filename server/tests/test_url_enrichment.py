"""Tests for URL enrichment helpers in the structured report agent.

Validates ``_is_base_url``, ``_find_url``, and
``_build_url_lookup`` to ensure that only base-domain URLs
are used in reports and that privacy/policy page URLs are
filtered out.
"""

from __future__ import annotations

import typing

import pytest

from src.agents.structured_report_agent import (
    _build_url_lookup,
    _find_url,
    _is_base_url,
)

# ── _is_base_url ───────────────────────────────────────────────


class TestIsBaseUrl:
    """Tests for the ``_is_base_url`` helper."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.sourcepoint.com",
            "https://www.google.com",
            "https://devowl.io/wordpress-real-cookie-banner/",
            "https://fundingchoices.google.com",
            "https://liveramp.com",
            "https://www.onetrust.com",
            "https://www.example.com/products/analytics",
            "https://www.example.com",
            "https://www.example.com/",
        ],
    )
    def test_accepts_base_urls(self, url: str) -> None:
        """Base/product URLs should pass the filter."""
        assert _is_base_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            # Explicit /privacy paths
            "https://www.reachplc.com/site-services/privacy-policy",
            "https://www.dailymail.co.uk/privacy",
            "https://www.example.com/privacy-notice/",
            "https://sourcepoint.com/privacy-notice/",
            # Cookie/policy paths
            "https://www.example.com/cookie-policy",
            "https://www.example.com/cookie-policy/",
            # Legal / GDPR paths
            "https://www.example.com/legal/terms",
            "https://www.example.com/gdpr/",
            "https://www.example.com/data-protection/",
            # Terms-of-service / terms-and-conditions
            "https://www.example.com/terms-of-service",
            "https://www.example.com/terms-and-conditions",
        ],
    )
    def test_rejects_privacy_urls(self, url: str) -> None:
        """Privacy/policy page URLs should be rejected."""
        assert _is_base_url(url) is False

    def test_empty_url(self) -> None:
        """Empty URL is treated as a base URL."""
        assert _is_base_url("") is True

    def test_root_path_only(self) -> None:
        """A URL with just a root path is a base URL."""
        assert _is_base_url("https://example.com/") is True


# ── _find_url ──────────────────────────────────────────────────


class TestFindUrl:
    """Tests for the ``_find_url`` fuzzy lookup."""

    LOOKUP: typing.ClassVar[dict[str, str]] = {
        "sourcepoint": "https://www.sourcepoint.com",
        "google": "https://www.google.com",
        "onetrust": "https://www.onetrust.com",
        "one trust": "https://www.onetrust.com",
    }

    def test_exact_match(self) -> None:
        """Exact lowercase match returns the URL."""
        assert _find_url("Sourcepoint", self.LOOKUP) == "https://www.sourcepoint.com"

    def test_substring_lookup_key_in_name(self) -> None:
        """Lookup key found as substring of name."""
        assert _find_url("Sourcepoint Technologies", self.LOOKUP) == "https://www.sourcepoint.com"

    def test_substring_name_in_key(self) -> None:
        """Name found as substring of lookup key."""
        assert _find_url("one trust", self.LOOKUP) == "https://www.onetrust.com"

    def test_no_match_returns_empty(self) -> None:
        """Unknown name returns empty string."""
        assert _find_url("Unknown Vendor", self.LOOKUP) == ""

    def test_case_insensitive(self) -> None:
        """Matching is case-insensitive."""
        assert _find_url("GOOGLE", self.LOOKUP) == "https://www.google.com"


# ── _build_url_lookup ─────────────────────────────────────────


class TestBuildUrlLookup:
    """Tests for the ``_build_url_lookup`` builder."""

    def test_contains_partner_db_entries(self) -> None:
        """Lookup should contain entries from partner DBs."""
        lookup = _build_url_lookup()
        assert "sourcepoint" in lookup
        assert lookup["sourcepoint"] == "https://www.sourcepoint.com"

    def test_contains_aliases(self) -> None:
        """Lookup should include alias-based entries."""
        lookup = _build_url_lookup()
        assert "one trust" in lookup
        assert lookup["one trust"] == "https://www.onetrust.com"

    def test_no_privacy_urls_in_lookup(self) -> None:
        """No URLs in the lookup should be privacy/policy pages."""
        lookup = _build_url_lookup()
        for name, url in lookup.items():
            assert _is_base_url(url), f"Privacy URL leaked into lookup: {name!r} → {url!r}"

    def test_all_cmps_have_urls(self) -> None:
        """Every consent-platform partner should be in lookup."""
        from src.data import loader

        cmp_db = loader.get_partner_database(
            "consent-platforms.json",
        )
        lookup = _build_url_lookup()
        for key, entry in cmp_db.items():
            if entry.url and _is_base_url(entry.url):
                assert key in lookup, f"CMP {key!r} missing from lookup"
