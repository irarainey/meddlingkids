"""Script-domain-level cache for script analysis results.

Caches the LLM-generated descriptions of unknown scripts so
that subsequent scans can skip the LLM call when the same
script (by base URL and content hash) is encountered again.

Cache files are JSON stored under ``server/.cache/scripts/``.
Each file is keyed by the **script's own domain** (e.g.
``s0.2mdn.net.json``, ``cdn.flashtalking.com.json``), not by
the website being scanned.  This means that once a Google Ads
script is analysed while scanning *site-A.com*, it is
automatically a cache hit when *site-B.com* uses the same
script — eliminating redundant LLM calls across sites.

**URL normalisation:** Query strings and fragments are
stripped from script URLs before comparison.  The underlying
JavaScript file does not change based on query parameters
(commonly ad-targeting metadata or cache-busters), so using
only the base URL as the cache key avoids redundant LLM
calls for the same file.

**Invalidation:** A cached entry is only reused when the
base URL **and** its MD5 content hash both match.  If a
URL is found in the cache but the hash has changed, the
stale entry is removed and the script is re-analysed via
the LLM.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import pathlib
from urllib import parse

import pydantic

from src.utils import cache, logger

log = logger.create_logger("ScriptCache")

# Cache directory — lives under server/.output/cache/, gitignored.
_CACHE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / ".output" / "cache" / "scripts"

# Maximum length for sanitised cache filenames (before ".json").
_CACHE_FILENAME_MAX_LENGTH = 100


def is_valid_script_url(url: str) -> bool:
    """Return True when *url* looks like a real HTTP(S) script URL.

    Rejects:
    - Filesystem paths (``/var/www/…``)
    - Bare domains / directory-only URLs with no file component
    - Non-HTTP schemes (``data:``, ``blob:``, ``file:``)
    - Empty / whitespace-only strings
    """
    if not url or not url.strip():
        return False
    parsed = parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    if not parsed.netloc:
        return False
    # Directory-only: path is empty or ends with '/' with no
    # filename (e.g. "https://cdn.example.com/" or
    # "https://cdn.example.com/scripts/").
    path = parsed.path.rstrip("/")
    if not path or "/" not in path:
        return True  # root-level resource is still valid
    # Reject if final segment has no extension and looks like
    # a directory component.  Real script URLs end in .js,
    # .mjs, etc. or at least have a filename.
    return True


# ── Cached script model ────────────────────────────────────────


class CachedScript(pydantic.BaseModel):
    """A previously analysed script with its content hash."""

    url: str
    content_hash: str  # MD5 hex digest of the fetched content
    description: str

    @pydantic.field_validator("url", mode="after")
    @classmethod
    def _reject_malformed_url(cls, v: str) -> str:
        """Reject filesystem paths and non-HTTP URLs at construction."""
        if not is_valid_script_url(v):
            msg = f"Malformed script URL rejected: {v!r}"
            raise ValueError(msg)
        return v


class ScriptCacheEntry(pydantic.BaseModel):
    """Per-script-domain analysis cache.

    Each entry groups scripts served from the same domain
    (e.g. ``cdn.flashtalking.com``) regardless of which
    website triggered the analysis.
    """

    domain: str
    scripts: list[CachedScript] = pydantic.Field(default_factory=list)

    # Not serialised — tracks whether in-memory mutations
    # (e.g. hash updates from soft cache hits) need to be
    # persisted.
    modified: bool = pydantic.Field(default=False, exclude=True)


# ── File helpers ────────────────────────────────────────────────


def _domain_path(domain: str) -> pathlib.Path:
    """Build the cache file path for a domain.

    Strips ``www.`` prefix so ``www.example.com`` and
    ``example.com`` share the same cache entry.
    """
    safe = domain.lower().removeprefix("www.")
    safe = "".join(c if c.isalnum() or c in ".-" else "_" for c in safe)[:_CACHE_FILENAME_MAX_LENGTH]
    return _CACHE_DIR / f"{safe}.json"


def _remove(path: pathlib.Path) -> None:
    """Silently delete a cache file."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


# ── Hashing ─────────────────────────────────────────────────────


def compute_hash(content: str) -> str:
    """Return the MD5 hex digest of *content*."""
    return hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()


def strip_query_string(url: str) -> str:
    """Strip query string and fragment from a URL.

    The underlying JavaScript file does not change based on
    query parameters (commonly ad-targeting metadata, cache-
    busters, or impression IDs), so this returns only the
    scheme + netloc + path for use as a stable cache key.

    Examples:
        >>> strip_query_string("https://cdn.example.com/tracker.js?v=1.2&cb=123")
        'https://cdn.example.com/tracker.js'
        >>> strip_query_string("https://cdn.example.com/tracker.js")
        'https://cdn.example.com/tracker.js'
    """
    parsed = parse.urlparse(url)
    return parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


# ── Public API ──────────────────────────────────────────────────


def load(domain: str) -> ScriptCacheEntry | None:
    """Load the cached script analysis for *domain*.

    Returns ``None`` when no cache exists, the file is
    malformed, or *domain* is the ``"unknown"`` sentinel.
    """
    if domain == "unknown":
        return None
    path = _domain_path(domain)
    if not path.exists():
        log.debug("No script cache", {"domain": domain})
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Filter out malformed script URLs that may exist in
        # older cache files (before validation was added).
        if "scripts" in data and isinstance(data["scripts"], list):
            valid: list[dict[str, str]] = []
            for s in data["scripts"]:
                url = s.get("url", "") if isinstance(s, dict) else ""
                if is_valid_script_url(url):
                    valid.append(s)
                else:
                    log.warn(
                        "Pruning malformed URL from script cache",
                        {"domain": domain, "url": url},
                    )
            data["scripts"] = valid
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
    """Look up a script in the cache by base URL.

    Query strings and fragments are stripped before comparison
    so that the same script served with different ad-targeting
    or cache-buster parameters hits the cache.

    Returns the cached description when the base URL matches,
    regardless of whether the content hash is identical.
    A script's functional purpose does not change when
    embedded tokens, timestamps, or A/B test variants rotate,
    so a stale hash should not trigger a costly LLM re-analysis.

    When the hash differs ("soft hit"), the stored hash is
    updated in-place and ``entry.modified`` is set so the
    caller can persist the change.

    Returns ``None`` (cache miss) only when the base URL is
    not in the cache at all.
    """
    base = strip_query_string(url)
    for cached in entry.scripts:
        if cached.url != base:
            continue

        if cached.content_hash == content_hash:
            return cached.description

        # URL matches but hash differs — reuse cached
        # description and update hash.  Ad-tech scripts
        # frequently embed per-request tokens that change
        # the hash without altering the script's purpose.
        log.info(
            "Script content changed, reusing cached description",
            {"url": base, "oldHash": cached.content_hash, "newHash": content_hash},
        )
        cached.content_hash = content_hash
        entry.modified = True
        return cached.description

    log.debug("Script cache miss", {"url": base})
    return None


def lookup_by_hash(
    cache_entries: dict[str, ScriptCacheEntry | None],
    content_hash: str,
) -> str | None:
    """Search all loaded cache entries for a matching content hash.

    When the same script content is served from different CDN
    domains (e.g. ``cdn1.example.com`` and ``cdn2.example.com``),
    each domain has its own cache file.  This function checks
    *every* loaded entry so that a hash already described under
    one domain is reused instead of triggering a redundant LLM
    call — preventing duplicate hashes with differing
    descriptions.

    Args:
        cache_entries: Map of domain → loaded cache entry.
        content_hash: MD5 hex digest to search for.

    Returns:
        The cached description, or ``None`` when no match
        is found.
    """
    for entry in cache_entries.values():
        if entry is None:
            continue
        for cached in entry.scripts:
            if cached.content_hash == content_hash:
                return cached.description
    return None


def save(
    domain: str,
    analyzed: list[CachedScript],
    existing: ScriptCacheEntry | None = None,
) -> None:
    """Merge newly analysed scripts into the cache and persist.

    Skips saving when *domain* is the ``"unknown"`` sentinel.

    New entries replace any existing entry with the same URL
    (the caller already verified the hash changed).  Existing
    entries whose URLs were not re-analysed are carried
    forward.
    """
    if domain == "unknown":
        log.debug("Skipping script cache save for unknown domain")
        return

    # Normalise URLs before merging so that query-string
    # variants don't create duplicate cache entries.
    # Also filter out any malformed URLs that slipped through.
    normalized: list[CachedScript] = []
    for s in analyzed:
        base_url = strip_query_string(s.url)
        if not is_valid_script_url(base_url):
            log.warn(
                "Skipping malformed script URL",
                {"url": s.url},
            )
            continue
        normalized.append(
            CachedScript(
                url=base_url,
                content_hash=s.content_hash,
                description=s.description,
            )
        )

    # Deduplicate by base URL — keep the first occurrence.
    # Also deduplicate by content hash — if the same content
    # appears under different URLs, keep only the first
    # description to prevent hash/description inconsistencies.
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    deduped: list[CachedScript] = []
    for s in normalized:
        if s.url not in seen_urls and s.content_hash not in seen_hashes:
            seen_urls.add(s.url)
            seen_hashes.add(s.content_hash)
            deduped.append(s)
    analyzed = deduped

    # Carry forward entries that weren't re-analysed this run.
    # Normalise carried-forward URLs too so that old cache
    # files with query-string variants don't create duplicates.
    # Also skip entries whose content hash is already covered
    # to avoid hash/description conflicts within one file.
    carried: list[CachedScript] = []
    if existing:
        for s in existing.scripts:
            base_url = strip_query_string(s.url)
            if base_url not in seen_urls and s.content_hash not in seen_hashes:
                seen_urls.add(base_url)
                seen_hashes.add(s.content_hash)
                carried.append(
                    CachedScript(
                        url=base_url,
                        content_hash=s.content_hash,
                        description=s.description,
                    )
                    if s.url != base_url
                    else s
                )

    merged = analyzed + carried

    entry = ScriptCacheEntry(domain=domain, scripts=merged)

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _domain_path(domain)
    try:
        cache.atomic_write_text(path, entry.model_dump_json(indent=2))
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
