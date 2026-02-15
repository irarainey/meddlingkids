"""Domain-level cache for overlay dismissal strategies.

Stores successful overlay detection and click information
per domain so subsequent analyses can skip expensive LLM
vision detection.  Cache files are JSON stored under
``server/.cache/overlay/``.

Cache entries are an **unordered** collection of strategies.
Different pages on the same domain may show different
subsets of overlays, so every cached strategy is tried
independently — those not present in the DOM are simply
skipped.

Each cached overlay records:
- The overlay type (cookie-consent, paywall, etc.)
- The button text used to dismiss it
- How Playwright located the element (locator strategy)
- Whether the element was on the main page or in a
  consent-manager iframe (frame type)
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Literal

import pydantic

from src.consent import constants
from src.utils import logger

log = logger.create_logger("OverlayCache")

LocatorStrategy = Literal[
    "role-button",
    "role-link",
    "text-exact",
    "text-fuzzy",
    "css",
    "generic-close",
]

FrameType = Literal["main", "consent-iframe"]

# Cache directory — lives alongside server source, gitignored.
_CACHE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / ".cache" / "overlay"


class CachedOverlay(pydantic.BaseModel):
    """A single cached overlay dismissal strategy.

    Stores exactly the information Playwright needs to
    locate and click the dismiss button on a repeat visit:
    the locator strategy, button text (or CSS selector),
    and whether the element lives in the main frame or a
    consent-manager iframe.
    """

    overlay_type: str
    button_text: str | None = None
    css_selector: str | None = None
    locator_strategy: LocatorStrategy = "role-button"
    frame_type: FrameType = "main"

    @pydantic.model_validator(mode="before")
    @classmethod
    def _migrate_legacy(cls, data: Any) -> Any:
        """Migrate old cache format (selector/accessor_type)."""
        if isinstance(data, dict):
            if "selector" in data and "css_selector" not in data:
                data["css_selector"] = data.pop("selector")
            elif "selector" in data:
                data.pop("selector")
            if "accessor_type" in data and "locator_strategy" not in data:
                _migration_map = {
                    "button-role": "role-button",
                    "css-selector": "css",
                    "text-search": "text-fuzzy",
                    "generic-close": "generic-close",
                }
                old = data.pop("accessor_type")
                data["locator_strategy"] = _migration_map.get(old, "role-button")
            elif "accessor_type" in data:
                data.pop("accessor_type")
        return data


class OverlayCacheEntry(pydantic.BaseModel):
    """Cached overlay information for a domain.

    Stores an **unordered** set of dismissal strategies.
    Each strategy is tried independently; those not
    present in the DOM are skipped.

    Duplicates are removed automatically on validation.
    """

    domain: str
    overlays: list[CachedOverlay]

    @pydantic.model_validator(mode="after")
    def _deduplicate_overlays(self) -> OverlayCacheEntry:
        """Remove duplicate overlays based on strategy + button text."""
        seen: set[str] = set()
        unique: list[CachedOverlay] = []
        for overlay in self.overlays:
            key = f"{overlay.locator_strategy}|{overlay.button_text or ''}|{overlay.css_selector or ''}"
            if key not in seen:
                seen.add(key)
                unique.append(overlay)
        self.overlays = unique
        return self


def _domain_path(domain: str) -> pathlib.Path:
    """Build the cache file path for a domain.

    Strips ``www.`` prefix so ``www.example.com`` and
    ``example.com`` share the same cache entry.  Invalid
    filesystem characters are replaced with underscores.
    """
    safe = domain.lower().removeprefix("www.")
    safe = "".join(c if c.isalnum() or c in ".-" else "_" for c in safe)[:100]
    return _CACHE_DIR / f"{safe}.json"


def load(domain: str) -> OverlayCacheEntry | None:
    """Load cached overlay info for *domain*.

    Returns ``None`` if no cache file exists or the file
    is malformed.
    """
    path = _domain_path(domain)
    if not path.exists():
        log.debug(
            "No overlay cache for domain",
            {
                "domain": domain,
            },
        )
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = OverlayCacheEntry.model_validate(data)
        log.info(
            "Overlay cache loaded",
            {
                "domain": domain,
                "overlays": len(entry.overlays),
            },
        )
        return entry
    except Exception as exc:
        log.warn(
            "Failed to read overlay cache, removing",
            {
                "domain": domain,
                "error": str(exc),
            },
        )
        _remove(path)
        return None


def save(entry: OverlayCacheEntry) -> None:
    """Persist an overlay cache entry to disk.

    Creates the cache directory if it does not exist.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _domain_path(entry.domain)
    try:
        path.write_text(
            entry.model_dump_json(indent=2),
            encoding="utf-8",
        )
        log.info(
            "Overlay cache saved",
            {
                "domain": entry.domain,
                "overlays": len(entry.overlays),
                "path": str(path.name),
            },
        )
    except Exception as exc:
        log.warn(
            "Failed to write overlay cache",
            {
                "domain": entry.domain,
                "error": str(exc),
            },
        )


def remove(domain: str) -> None:
    """Delete the cache file for *domain* (if it exists)."""
    path = _domain_path(domain)
    _remove(path)


def _remove(path: pathlib.Path) -> None:
    """Delete a cache file, logging the outcome."""
    if path.exists():
        try:
            path.unlink()
            log.info(
                "Overlay cache removed",
                {
                    "path": str(path.name),
                },
            )
        except Exception as exc:
            log.warn(
                "Failed to remove overlay cache",
                {
                    "path": str(path.name),
                    "error": str(exc),
                },
            )


def merge_and_save(
    domain: str,
    previous_entry: OverlayCacheEntry | None,
    new_overlays: list[CachedOverlay],
    failed_types: set[str],
) -> None:
    """Merge previous cache with new detections and persist.

    Combines three sources:

    1. Previous cache entries whose overlays did not fail.
    2. Newly dismissed overlays from this run.

    Entries whose overlay type is in *failed_types* are
    dropped.  Duplicates are removed by selector/button key.

    Args:
        domain: The domain to save the cache for.
        previous_entry: Existing cache entry (may be ``None``).
        new_overlays: Overlays dismissed in this run.
        failed_types: Overlay types whose clicks failed.
    """
    # Regex for reject-style button text that should be
    # dropped from cache when an accept alternative exists.
    _reject_re = constants.REJECT_BUTTON_RE

    seen_keys: set[str] = set()
    overlays: list[CachedOverlay] = []

    # Carry forward previous entries that didn't fail.
    carried_forward = 0
    dropped = 0
    if previous_entry:
        for cached in previous_entry.overlays:
            if cached.overlay_type in failed_types:
                dropped += 1
                continue
            key = f"{cached.locator_strategy}|{cached.button_text or ''}|{cached.css_selector or ''}"
            if key not in seen_keys:
                seen_keys.add(key)
                overlays.append(cached)
                carried_forward += 1

    # Add new overlays.
    added_new = 0
    for overlay in new_overlays:
        key = f"{overlay.locator_strategy}|{overlay.button_text or ''}|{overlay.css_selector or ''}"
        if key not in seen_keys:
            seen_keys.add(key)
            overlays.append(overlay)
            added_new += 1

    # Drop reject-style cookie-consent entries when an
    # accept alternative for the same overlay type exists.
    # This prevents stale reject entries from accumulating
    # in the cache after an accept override.
    consent_types = {o.overlay_type for o in overlays if o.overlay_type == "cookie-consent"}
    if "cookie-consent" in consent_types:
        has_accept = any(o.overlay_type == "cookie-consent" and o.button_text and not _reject_re.search(o.button_text) for o in overlays)
        if has_accept:
            overlays = [
                o for o in overlays if not (o.overlay_type == "cookie-consent" and o.button_text and _reject_re.search(o.button_text))
            ]

    if not overlays:
        remove(domain)
        return

    log.info(
        "Overlay cache merge",
        {
            "domain": domain,
            "carriedForward": carried_forward,
            "newOverlays": added_new,
            "dropped": dropped,
            "total": len(overlays),
        },
    )

    entry = OverlayCacheEntry(
        domain=domain,
        overlays=overlays,
    )
    save(entry)
