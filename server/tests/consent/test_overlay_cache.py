"""Tests for src.consent.overlay_cache — overlay dismissal strategy caching."""

from __future__ import annotations

from src.consent.overlay_cache import (
    CachedOverlay,
    OverlayCacheEntry,
    _domain_path,
    backfill_consent_platform,
    load,
    merge_and_save,
    remove,
    save,
)


class TestCachedOverlay:
    """Tests for CachedOverlay model and migration."""

    def test_basic_creation(self) -> None:
        overlay = CachedOverlay(
            overlay_type="cookie-consent",
            button_text="Accept All",
        )
        assert overlay.overlay_type == "cookie-consent"
        assert overlay.button_text == "Accept All"
        assert overlay.locator_strategy == "role-button"
        assert overlay.frame_type == "main"

    def test_legacy_selector_migration(self) -> None:
        data = {
            "overlay_type": "cookie-consent",
            "selector": ".accept-btn",
            "accessor_type": "css-selector",
        }
        overlay = CachedOverlay.model_validate(data)
        assert overlay.css_selector == ".accept-btn"
        assert overlay.locator_strategy == "css"

    def test_legacy_button_role_migration(self) -> None:
        data = {
            "overlay_type": "cookie-consent",
            "button_text": "OK",
            "accessor_type": "button-role",
        }
        overlay = CachedOverlay.model_validate(data)
        assert overlay.locator_strategy == "role-button"

    def test_legacy_text_search_migration(self) -> None:
        data = {
            "overlay_type": "cookie-consent",
            "button_text": "Accept",
            "accessor_type": "text-search",
        }
        overlay = CachedOverlay.model_validate(data)
        assert overlay.locator_strategy == "text-fuzzy"

    def test_legacy_generic_close_migration(self) -> None:
        data = {
            "overlay_type": "newsletter",
            "accessor_type": "generic-close",
        }
        overlay = CachedOverlay.model_validate(data)
        assert overlay.locator_strategy == "generic-close"

    def test_legacy_unknown_accessor_type(self) -> None:
        data = {
            "overlay_type": "cookie-consent",
            "accessor_type": "unknown-strategy",
        }
        overlay = CachedOverlay.model_validate(data)
        assert overlay.locator_strategy == "role-button"

    def test_both_selector_and_css_selector(self) -> None:
        data = {
            "overlay_type": "cookie-consent",
            "selector": ".old",
            "css_selector": ".new",
        }
        overlay = CachedOverlay.model_validate(data)
        assert overlay.css_selector == ".new"


class TestOverlayCacheEntry:
    """Tests for OverlayCacheEntry deduplication."""

    def test_deduplicates_overlays(self) -> None:
        overlays = [
            CachedOverlay(overlay_type="cookie-consent", button_text="Accept"),
            CachedOverlay(overlay_type="cookie-consent", button_text="Accept"),
        ]
        entry = OverlayCacheEntry(domain="example.com", overlays=overlays)
        assert len(entry.overlays) == 1

    def test_different_strategies_not_deduplicated(self) -> None:
        overlays = [
            CachedOverlay(overlay_type="cookie-consent", button_text="Accept", locator_strategy="role-button"),
            CachedOverlay(overlay_type="cookie-consent", button_text="Accept", locator_strategy="text-fuzzy"),
        ]
        entry = OverlayCacheEntry(domain="example.com", overlays=overlays)
        assert len(entry.overlays) == 2


class TestDomainPath:
    """Tests for _domain_path computation."""

    def test_strips_www(self) -> None:
        path = _domain_path("www.example.com")
        assert "www." not in path.name

    def test_lowercases(self) -> None:
        path = _domain_path("EXAMPLE.COM")
        assert path.name == "example.com.json"

    def test_safe_characters(self) -> None:
        path = _domain_path("ex@mple:com")
        assert "@" not in path.name
        assert ":" not in path.name

    def test_max_length(self) -> None:
        path = _domain_path("a" * 200 + ".com")
        assert len(path.stem) <= 100


class TestLoadAndSave:
    """Tests for load / save / remove cycle."""

    def test_load_unknown_domain_returns_none(self) -> None:
        result = load("unknown")
        assert result is None

    def test_load_nonexistent_returns_none(self) -> None:
        result = load("nonexistent-domain-xyz123456.com")
        assert result is None

    def test_save_and_load_cycle(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.consent.overlay_cache._CACHE_DIR", tmp_path)
        entry = OverlayCacheEntry(
            domain="test.com",
            overlays=[
                CachedOverlay(overlay_type="cookie-consent", button_text="Accept"),
            ],
        )
        save(entry)
        loaded = load("test.com")
        assert loaded is not None
        assert len(loaded.overlays) == 1
        assert loaded.overlays[0].button_text == "Accept"

    def test_save_unknown_domain_skipped(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.consent.overlay_cache._CACHE_DIR", tmp_path)
        entry = OverlayCacheEntry(domain="unknown", overlays=[])
        save(entry)
        assert not list(tmp_path.iterdir())

    def test_remove_nonexistent_no_error(self) -> None:
        remove("completely-nonexistent-domain-xyz.com")

    def test_remove_existing(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.consent.overlay_cache._CACHE_DIR", tmp_path)
        entry = OverlayCacheEntry(
            domain="removeme.com",
            overlays=[CachedOverlay(overlay_type="cookie-consent", button_text="OK")],
        )
        save(entry)
        remove("removeme.com")
        result = load("removeme.com")
        assert result is None

    def test_load_malformed_file(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.consent.overlay_cache._CACHE_DIR", tmp_path)
        bad_file = tmp_path / "bad.com.json"
        bad_file.write_text("not valid json {{", encoding="utf-8")
        result = load("bad.com")
        assert result is None
        assert not bad_file.exists()


class TestBackfillConsentPlatform:
    """Tests for backfill_consent_platform()."""

    def test_backfills_missing_platform(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.consent.overlay_cache._CACHE_DIR", tmp_path)
        entry = OverlayCacheEntry(
            domain="example.com",
            overlays=[
                CachedOverlay(overlay_type="cookie-consent", button_text="Accept"),
            ],
        )
        save(entry)
        backfill_consent_platform("example.com", "onetrust")
        loaded = load("example.com")
        assert loaded is not None
        assert loaded.overlays[0].consent_platform == "onetrust"

    def test_skips_when_platform_already_set(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.consent.overlay_cache._CACHE_DIR", tmp_path)
        entry = OverlayCacheEntry(
            domain="example.com",
            overlays=[
                CachedOverlay(
                    overlay_type="cookie-consent",
                    button_text="Accept",
                    consent_platform="cookiebot",
                ),
            ],
        )
        save(entry)
        backfill_consent_platform("example.com", "onetrust")
        loaded = load("example.com")
        assert loaded is not None
        assert loaded.overlays[0].consent_platform == "cookiebot"

    def test_skips_non_consent_overlays(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.consent.overlay_cache._CACHE_DIR", tmp_path)
        entry = OverlayCacheEntry(
            domain="example.com",
            overlays=[
                CachedOverlay(overlay_type="newsletter", button_text="Close"),
            ],
        )
        save(entry)
        backfill_consent_platform("example.com", "onetrust")
        loaded = load("example.com")
        assert loaded is not None
        assert loaded.overlays[0].consent_platform is None

    def test_backfill_no_cache_entry(self) -> None:
        backfill_consent_platform("nonexistent-domain-xyz.com", "onetrust")


class TestMergeAndSave:
    """Tests for merge_and_save()."""

    def test_merge_new_overlays(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.consent.overlay_cache._CACHE_DIR", tmp_path)
        new_overlays = [
            CachedOverlay(overlay_type="cookie-consent", button_text="Accept All"),
        ]
        merge_and_save("test.com", None, new_overlays, set())
        loaded = load("test.com")
        assert loaded is not None
        assert len(loaded.overlays) == 1

    def test_merge_carries_forward_previous(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.consent.overlay_cache._CACHE_DIR", tmp_path)
        previous = OverlayCacheEntry(
            domain="test.com",
            overlays=[
                CachedOverlay(overlay_type="newsletter", button_text="Close"),
            ],
        )
        new_overlays = [
            CachedOverlay(overlay_type="cookie-consent", button_text="Accept"),
        ]
        merge_and_save("test.com", previous, new_overlays, set())
        loaded = load("test.com")
        assert loaded is not None
        assert len(loaded.overlays) == 2

    def test_merge_drops_failed_types(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.consent.overlay_cache._CACHE_DIR", tmp_path)
        previous = OverlayCacheEntry(
            domain="test.com",
            overlays=[
                CachedOverlay(overlay_type="cookie-consent", button_text="Old Accept"),
            ],
        )
        merge_and_save("test.com", previous, [], {"cookie-consent"})
        loaded = load("test.com")
        assert loaded is None

    def test_merge_deduplicates(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.consent.overlay_cache._CACHE_DIR", tmp_path)
        previous = OverlayCacheEntry(
            domain="test.com",
            overlays=[
                CachedOverlay(overlay_type="cookie-consent", button_text="Accept"),
            ],
        )
        new_overlays = [
            CachedOverlay(overlay_type="cookie-consent", button_text="Accept"),
        ]
        merge_and_save("test.com", previous, new_overlays, set())
        loaded = load("test.com")
        assert loaded is not None
        assert len(loaded.overlays) == 1

    def test_merge_drops_reject_when_accept_exists(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.consent.overlay_cache._CACHE_DIR", tmp_path)
        new_overlays = [
            CachedOverlay(overlay_type="cookie-consent", button_text="Accept All"),
            CachedOverlay(overlay_type="cookie-consent", button_text="Reject All"),
        ]
        merge_and_save("test.com", None, new_overlays, set())
        loaded = load("test.com")
        assert loaded is not None
        # Reject should be dropped when accept exists
        texts = [o.button_text for o in loaded.overlays]
        assert "Accept All" in texts

    def test_merge_empty_removes_cache(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr("src.consent.overlay_cache._CACHE_DIR", tmp_path)
        merge_and_save("test.com", None, [], set())
        loaded = load("test.com")
        assert loaded is None
