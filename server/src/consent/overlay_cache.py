"""Domain-level cache for overlay dismissal strategies.

Stores successful overlay detection and click information
per domain so subsequent analyses can skip expensive LLM
vision detection.  Cache files are JSON stored under
``server/.overlay_cache/``.

Cache entries are an **unordered** collection of strategies.
Different pages on the same domain may show different
subsets of overlays, so every cached strategy is tried
independently — those not present in the DOM are simply
skipped.

Each cached overlay records:
- The overlay type (cookie-consent, paywall, etc.)
- The button text used to dismiss it
- The CSS selector (if any)
- How the element was located (accessor type)
"""

from __future__ import annotations

import json
import pathlib
from typing import Literal

import pydantic
from src.utils import logger

log = logger.create_logger("OverlayCache")

AccessorType = Literal[
    "button-role",
    "css-selector",
    "text-search",
    "generic-close",
]

# Cache directory — lives alongside server source, gitignored.
_CACHE_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / ".overlay_cache"
)


class CachedOverlay(pydantic.BaseModel):
    """A single cached overlay dismissal strategy."""

    overlay_type: str
    button_text: str | None = None
    selector: str | None = None
    accessor_type: AccessorType


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
    def _deduplicate_overlays(self) -> "OverlayCacheEntry":
        """Remove duplicate overlays based on selector + button text."""
        seen: set[str] = set()
        unique: list[CachedOverlay] = []
        for overlay in self.overlays:
            key = f"{overlay.selector or ''}|{overlay.button_text or ''}"
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
    safe = domain.lower().lstrip("www.")
    safe = "".join(
        c if c.isalnum() or c in ".-" else "_"
        for c in safe
    )[:100]
    return _CACHE_DIR / f"{safe}.json"


def load(domain: str) -> OverlayCacheEntry | None:
    """Load cached overlay info for *domain*.

    Returns ``None`` if no cache file exists or the file
    is malformed.
    """
    path = _domain_path(domain)
    if not path.exists():
        log.debug("No overlay cache for domain", {
            "domain": domain,
        })
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = OverlayCacheEntry.model_validate(data)
        log.info("Overlay cache loaded", {
            "domain": domain,
            "overlays": len(entry.overlays),
        })
        return entry
    except Exception as exc:
        log.warn("Failed to read overlay cache, removing", {
            "domain": domain,
            "error": str(exc),
        })
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
        log.info("Overlay cache saved", {
            "domain": entry.domain,
            "overlays": len(entry.overlays),
            "path": str(path.name),
        })
    except Exception as exc:
        log.warn("Failed to write overlay cache", {
            "domain": entry.domain,
            "error": str(exc),
        })


def remove(domain: str) -> None:
    """Delete the cache file for *domain* (if it exists)."""
    path = _domain_path(domain)
    _remove(path)


def _remove(path: pathlib.Path) -> None:
    """Delete a cache file, logging the outcome."""
    if path.exists():
        try:
            path.unlink()
            log.info("Overlay cache removed", {
                "path": str(path.name),
            })
        except Exception as exc:
            log.warn("Failed to remove overlay cache", {
                "path": str(path.name),
                "error": str(exc),
            })
