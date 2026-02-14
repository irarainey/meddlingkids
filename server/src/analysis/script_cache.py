"""Domain-level cache for script analysis results.

Caches the LLM-generated descriptions of unknown scripts so
that subsequent scans of the same domain can skip the LLM
call when the same script (by URL and content hash) is
encountered again.

Cache files are JSON stored under ``server/.cache/scripts/``.
Each file is named by the base domain (``www.`` stripped).

**Invalidation:** A cached entry is only reused when the
script URL **and** its MD5 content hash both match.  If a
URL is found in the cache but the hash has changed, the
stale entry is removed and the script is re-analysed via
the LLM.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import pathlib

import pydantic

from src.utils import logger

log = logger.create_logger("ScriptCache")

# Cache directory — lives alongside server source, gitignored.
_CACHE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / ".cache" / "scripts"


# ── Cached script model ────────────────────────────────────────


class CachedScript(pydantic.BaseModel):
    """A previously analysed script with its content hash."""

    url: str
    content_hash: str  # MD5 hex digest of the fetched content
    description: str


class ScriptCacheEntry(pydantic.BaseModel):
    """Per-domain script analysis cache."""

    domain: str
    scripts: list[CachedScript] = pydantic.Field(default_factory=list)


# ── File helpers ────────────────────────────────────────────────


def _domain_path(domain: str) -> pathlib.Path:
    """Build the cache file path for a domain.

    Strips ``www.`` prefix so ``www.example.com`` and
    ``example.com`` share the same cache entry.
    """
    safe = domain.lower().removeprefix("www.")
    safe = "".join(c if c.isalnum() or c in ".-" else "_" for c in safe)[:100]
    return _CACHE_DIR / f"{safe}.json"


def _remove(path: pathlib.Path) -> None:
    """Silently delete a cache file."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


# ── Hashing ─────────────────────────────────────────────────────


def compute_hash(content: str) -> str:
    """Return the MD5 hex digest of *content*."""
    return hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()


# ── Public API ──────────────────────────────────────────────────


def load(domain: str) -> ScriptCacheEntry | None:
    """Load the cached script analysis for *domain*.

    Returns ``None`` when no cache exists or the file is
    malformed.
    """
    path = _domain_path(domain)
    if not path.exists():
        log.debug("No script cache", {"domain": domain})
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = ScriptCacheEntry.model_validate(data)
        log.info(
            "Script cache loaded",
            {"domain": domain, "scripts": len(entry.scripts)},
        )
        return entry
    except Exception as exc:
        log.warn(
            "Failed to read script cache, removing",
            {"domain": domain, "error": str(exc)},
        )
        _remove(path)
        return None


def lookup(
    entry: ScriptCacheEntry,
    url: str,
    content_hash: str,
) -> str | None:
    """Look up a script in the cache by URL and content hash.

    Returns the cached description if both the URL and hash
    match.  Returns ``None`` (cache miss) if:
    - The URL is not in the cache, or
    - The URL is present but the hash differs (content changed).

    A hash mismatch also removes the stale entry so it will
    be replaced on save.
    """
    for i, cached in enumerate(entry.scripts):
        if cached.url != url:
            continue

        if cached.content_hash == content_hash:
            return cached.description

        # URL matches but hash differs — invalidate.
        log.info(
            "Script content changed, invalidating cache entry",
            {"url": url, "oldHash": cached.content_hash, "newHash": content_hash},
        )
        entry.scripts.pop(i)
        return None

    log.debug("Script cache miss", {"url": url})
    return None


def save(
    domain: str,
    analyzed: list[CachedScript],
    existing: ScriptCacheEntry | None = None,
) -> None:
    """Merge newly analysed scripts into the cache and persist.

    New entries replace any existing entry with the same URL
    (the caller already verified the hash changed).  Existing
    entries whose URLs were not re-analysed are carried
    forward.
    """
    new_urls = {s.url for s in analyzed}

    # Carry forward entries that weren't re-analysed this run.
    carried: list[CachedScript] = []
    if existing:
        carried = [s for s in existing.scripts if s.url not in new_urls]

    merged = analyzed + carried

    entry = ScriptCacheEntry(domain=domain, scripts=merged)

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _domain_path(domain)
    try:
        path.write_text(entry.model_dump_json(indent=2), encoding="utf-8")
        log.info(
            "Script cache saved",
            {
                "domain": domain,
                "newScripts": len(analyzed),
                "carriedForward": len(carried),
                "total": len(merged),
                "path": str(path.name),
            },
        )
    except Exception as exc:
        log.warn(
            "Failed to write script cache",
            {"domain": domain, "error": str(exc)},
        )
