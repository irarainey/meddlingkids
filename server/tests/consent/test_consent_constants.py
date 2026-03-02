"""Tests for src.consent.constants — consent detection constants."""

from __future__ import annotations

from unittest import mock

from src.consent.constants import (
    CONSENT_CONTAINER_SELECTORS,
    CONSENT_HOST_EXCLUDE,
    CONSENT_HOST_KEYWORDS,
    REJECT_BUTTON_RE,
    is_consent_frame,
)


class TestConsentHostKeywords:
    def test_is_tuple(self) -> None:
        assert isinstance(CONSENT_HOST_KEYWORDS, tuple)

    def test_includes_known_cmps(self) -> None:
        for kw in ("onetrust", "cookiebot", "sourcepoint", "didomi", "quantcast"):
            assert kw in CONSENT_HOST_KEYWORDS


class TestConsentHostExclude:
    def test_is_tuple(self) -> None:
        assert isinstance(CONSENT_HOST_EXCLUDE, tuple)

    def test_excludes_ad_tech(self) -> None:
        for kw in ("pixel", "-sync.", "prebid"):
            assert kw in CONSENT_HOST_EXCLUDE


class TestConsentContainerSelectors:
    def test_is_tuple(self) -> None:
        assert isinstance(CONSENT_CONTAINER_SELECTORS, tuple)

    def test_includes_known_selectors(self) -> None:
        selector_str = " ".join(CONSENT_CONTAINER_SELECTORS)
        assert "#onetrust-banner-sdk" in selector_str
        assert "#CybotCookiebotDialog" in selector_str
        assert "#qc-cmp2-ui" in selector_str


class TestRejectButtonRegex:
    def test_matches_reject_variants(self) -> None:
        for text in ("Reject All", "Decline", "Deny Cookies", "Refuse", "Necessary Only", "Essential only"):
            assert REJECT_BUTTON_RE.search(text), f"Should match {text!r}"

    def test_no_match_for_accept(self) -> None:
        for text in ("Accept All", "Allow", "OK", "Got it"):
            assert not REJECT_BUTTON_RE.search(text), f"Should NOT match {text!r}"


class TestIsConsentFrame:
    """Uses mock Frame objects instead of real Playwright frames."""

    @staticmethod
    def _make_frame(url: str, *, is_main: bool = False) -> mock.MagicMock:
        frame = mock.MagicMock()
        frame.url = url
        return frame

    def test_main_frame_returns_false(self) -> None:
        main = self._make_frame("https://example.com")
        assert is_consent_frame(main, main) is False

    def test_consent_iframe_returns_true(self) -> None:
        main = self._make_frame("https://example.com")
        child = self._make_frame("https://consent.onetrust.com/dialog")
        assert is_consent_frame(child, main) is True

    def test_non_consent_iframe_returns_false(self) -> None:
        main = self._make_frame("https://example.com")
        child = self._make_frame("https://cdn.someadnetwork.com/widget.js")
        assert is_consent_frame(child, main) is False

    def test_ad_sync_excluded(self) -> None:
        """An iframe with consent keyword BUT also an exclusion keyword is excluded."""
        main = self._make_frame("https://example.com")
        child = self._make_frame("https://cookie-sync.consent-platform.com/sync")
        assert is_consent_frame(child, main) is False

    def test_privacy_keyword_matches(self) -> None:
        main = self._make_frame("https://example.com")
        child = self._make_frame("https://privacy.company.com/notice")
        assert is_consent_frame(child, main) is True

    def test_gdpr_query_param_not_false_positive(self) -> None:
        """Only hostname is checked — query params should NOT trigger a match."""
        main = self._make_frame("https://example.com")
        child = self._make_frame("https://ads.network.com/pixel?gdpr=1&gdpr_consent=abc")
        assert is_consent_frame(child, main) is False
