"""Script analysis service.

Analyses JavaScript files to determine their purpose.
Groups similar scripts (like application chunks), matches
against known patterns, and delegates only truly unknown
scripts to the ``ScriptAnalysisAgent`` for LLM-based
identification — each script analysed individually with
concurrent execution bounded by a semaphore.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import aiohttp
import pydantic

from src import agents
from src.analysis import script_cache, script_grouping
from src.data import loader
from src.models import tracking_data
from src.utils import logger
from src.utils import url as url_mod

log = logger.create_logger("Script-Analysis")

# Maximum number of concurrent LLM calls for script analysis.
# Each call is tiny (~2 K prompt, 200 max tokens) so the
# endpoint comfortably handles higher parallelism.
MAX_CONCURRENCY = 10


# ============================================================================
# Known script identification
# ============================================================================


def _identify_tracking_script(url: str) -> str | None:
    """Check if a script is a known tracking script."""
    for entry in loader.get_tracking_scripts():
        if entry.compiled.search(url):
            return entry.description
    return None


def _identify_benign_script(url: str) -> str | None:
    """Check if a script is a known benign script (skip LLM analysis)."""
    for entry in loader.get_benign_scripts():
        if entry.compiled.search(url):
            return entry.description
    return None


def _identify_tracker_domain(domain: str) -> str | None:
    """Check if a script's domain is a known tracker.

    Uses the tracker-domains database and Disconnect services to
    produce a descriptive label.  Returns ``None`` when the domain
    is not recognised.
    """
    if not loader.is_known_tracker_domain(domain):
        return None

    category = loader.get_disconnect_category(domain)
    if category:
        cat_label = ", ".join(category) if isinstance(category, list) else category
        services = loader.get_disconnect_services()
        info = services.get(domain)
        if not info:
            base = url_mod.get_base_domain(domain)
            info = services.get(base)
        company = info.get("company") if info else None
        if company:
            return f"Known tracker: {company} ({cat_label})"
        return f"Known tracker ({cat_label})"
    return "Known tracking domain"


# ============================================================================
# Content fetching
# ============================================================================

_FETCH_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SecurityAnalyzer/1.0)"}
_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=5)

# Limit redirects to prevent secondary SSRF via 302 chains
# from malicious pages.  Scripts should rarely redirect more
# than once (CDN → origin).
_MAX_REDIRECTS = 3


# Maximum bytes to read from a single script fetch.  Large
# scripts (e.g. bundled vendor files) can exceed 10 MB; there
# is no value in downloading the full content since the LLM
# agent truncates to 2 000 chars anyway.
_MAX_SCRIPT_BYTES = 128 * 1024  # 128 KB


async def _fetch_script_content(
    url: str,
    http_session: aiohttp.ClientSession,
    retries: int = 2,
) -> str | None:
    """Fetch a script's content for analysis with retry.

    Accepts a shared ``aiohttp.ClientSession`` so that TCP
    connections are reused across many concurrent fetches.

    Only the first ``_MAX_SCRIPT_BYTES`` bytes are read to
    prevent excessive memory use from very large bundles.
    """
    for attempt in range(retries + 1):
        try:
            async with http_session.get(
                url,
                headers=_FETCH_HEADERS,
                max_redirects=_MAX_REDIRECTS,
            ) as response:
                if response.status >= 400:
                    if attempt < retries and (response.status >= 500 or response.status == 429):
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    log.debug("Script fetch failed", {"url": url, "status": response.status})
                    return None
                body = await response.content.read(_MAX_SCRIPT_BYTES)
                extra = await response.content.read(1)
                truncated = len(extra) > 0
                text = body.decode("utf-8", errors="replace")
                if truncated:
                    log.debug(
                        "Script content truncated",
                        {"url": url, "maxBytes": _MAX_SCRIPT_BYTES},
                    )
                return text
        except Exception as exc:
            if attempt < retries:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            log.debug("Script fetch error", {"url": url, "error": str(exc)})
            return None
    return None


# ============================================================================
# LLM analysis
# ============================================================================


async def _analyze_one_with_llm(
    url: str,
    content: str | None,
) -> tuple[str, str]:
    """Analyse a single script via the LLM agent.

    Args:
        url: Script URL.
        content: Fetched script content (may be *None*).

    Returns:
        A ``(url, description)`` tuple.
    """
    agent = agents.get_script_analysis_agent()
    if not agent.is_configured:
        return url, _infer_from_url(url)

    description = await agent.analyze_one(url, content)
    return url, description or _infer_from_url(url)


def _infer_from_url(url: str) -> str:
    """Infer a script's purpose from its URL when content is unavailable."""
    url_lower = url.lower()
    if "analytics" in url_lower:
        return "Analytics script"
    if "tracking" in url_lower or "tracker" in url_lower:
        return "Tracking script"
    if "pixel" in url_lower:
        return "Tracking pixel"
    if any(kw in url_lower for kw in ("consent", "gdpr", "privacy")):
        return "Consent/privacy related"
    if "chat" in url_lower or "widget" in url_lower:
        return "Chat or widget script"
    if "ads" in url_lower or "advert" in url_lower:
        return "Advertising script"
    if "social" in url_lower or "share" in url_lower:
        return "Social sharing script"
    if "vendor" in url_lower or "third-party" in url_lower:
        return "Third-party vendor script"
    if "polyfill" in url_lower:
        return "Browser compatibility polyfill"
    if any(kw in url_lower for kw in ("main", "app", "bundle")):
        return "Application bundle"
    if "chunk" in url_lower:
        return "Code-split chunk"
    return "Third-party script"


# All possible return values from ``_infer_from_url``.
# Used to detect fallback descriptions that should NOT
# be persisted to the script cache.
_FALLBACK_DESCRIPTIONS: frozenset[str] = frozenset(
    {
        "Analytics script",
        "Tracking script",
        "Tracking pixel",
        "Consent/privacy related",
        "Chat or widget script",
        "Advertising script",
        "Social sharing script",
        "Third-party vendor script",
        "Browser compatibility polyfill",
        "Application bundle",
        "Code-split chunk",
        "Third-party script",
    }
)


def is_fallback_description(description: str) -> bool:
    """Check whether a description is a URL-heuristic fallback.

    Fallback descriptions are generic labels produced by
    ``_infer_from_url`` when the LLM agent is unavailable
    or fails.  They should not be cached because they would
    mask real LLM results once the agent is fixed.

    Args:
        description: The script description to check.

    Returns:
        ``True`` when the description matches a known fallback.
    """
    return description in _FALLBACK_DESCRIPTIONS


# Type alias for progress callback
ScriptAnalysisProgressCallback = Callable[[str, int, int, str], None]


class ScriptAnalysisResult(pydantic.BaseModel):
    """Result of analyzing a set of scripts."""

    scripts: list[tracking_data.TrackedScript] = pydantic.Field(default_factory=list)
    groups: list[tracking_data.ScriptGroup] = pydantic.Field(default_factory=list)


async def analyze_scripts(
    scripts: list[tracking_data.TrackedScript],
    on_progress: ScriptAnalysisProgressCallback | None = None,
) -> ScriptAnalysisResult:
    """Analyze multiple scripts to determine their purposes.

    Process:
    1. Group similar scripts (chunks, vendor bundles) — skip LLM analysis
    2. Match remaining against known patterns (tracking + benign)
    3. Check the per-script-domain cache for previously analysed scripts
    4. Send only uncached unknown scripts to the LLM agent concurrently
    5. Save newly analysed scripts to the cache (keyed by script domain)
    """
    grouped = script_grouping.group_similar_scripts(scripts)
    results: list[tracking_data.TrackedScript] = list(grouped.all_scripts)

    unknown_scripts = _match_known_patterns(results, grouped, on_progress)

    if unknown_scripts:
        await _analyze_unknowns(results, unknown_scripts, on_progress)
    else:
        log.info("All scripts identified from patterns or grouped, no LLM analysis needed")
        if on_progress:
            on_progress("analyzing", 0, 0, "All scripts identified from patterns or grouped")

    return ScriptAnalysisResult(scripts=results, groups=grouped.groups)


def _match_known_patterns(
    results: list[tracking_data.TrackedScript],
    grouped: script_grouping.GroupedScriptsResult,
    on_progress: ScriptAnalysisProgressCallback | None,
) -> list[tuple[tracking_data.TrackedScript, int]]:
    """Match non-grouped scripts against known tracking/benign patterns.

    Returns a list of ``(script, result_index)`` tuples for scripts
    that could not be identified from patterns and need LLM analysis.
    Mutates *results* in-place for identified scripts.
    """
    unknown_scripts: list[tuple[tracking_data.TrackedScript, int]] = []
    grouped_count = sum(1 for s in grouped.all_scripts if s.is_grouped)
    tracking_pattern_hits = 0
    tracker_domain_hits = 0
    benign_pattern_hits = 0

    if on_progress:
        detail = (
            f"Grouped {grouped_count} similar scripts, matching {len(grouped.individual_scripts)} against known patterns..."
            if grouped_count > 0
            else "Matching scripts against known patterns..."
        )
        on_progress("matching", 0, len(grouped.individual_scripts), detail)

    for i, script in enumerate(results):
        if script.is_grouped:
            continue

        tracking_desc = _identify_tracking_script(script.url)
        if tracking_desc:
            tracking_pattern_hits += 1
            results[i] = tracking_data.TrackedScript(
                url=script.url,
                domain=script.domain,
                description=tracking_desc,
                resource_type=script.resource_type,
            )
            continue

        tracker_domain_desc = _identify_tracker_domain(script.domain)
        if tracker_domain_desc:
            tracker_domain_hits += 1
            results[i] = tracking_data.TrackedScript(
                url=script.url,
                domain=script.domain,
                description=tracker_domain_desc,
                resource_type=script.resource_type,
            )
            continue

        benign_desc = _identify_benign_script(script.url)
        if benign_desc:
            benign_pattern_hits += 1
            results[i] = tracking_data.TrackedScript(
                url=script.url,
                domain=script.domain,
                description=benign_desc,
                resource_type=script.resource_type,
            )
            continue

        results[i] = tracking_data.TrackedScript(
            url=script.url,
            domain=script.domain,
            description="Analyzing...",
            resource_type=script.resource_type,
        )
        unknown_scripts.append((script, i))

    parts: list[str] = []
    if grouped_count:
        parts.append(f"{grouped_count} grouped")
    if tracking_pattern_hits:
        parts.append(f"{tracking_pattern_hits} tracking")
    if tracker_domain_hits:
        parts.append(f"{tracker_domain_hits} known domains")
    if benign_pattern_hits:
        parts.append(f"{benign_pattern_hits} benign")
    summary = ", ".join(parts) if parts else "0 known"
    if on_progress:
        on_progress(
            "matching",
            len(grouped.individual_scripts),
            len(grouped.individual_scripts),
            f"Identified {summary} — {len(unknown_scripts)} to analyze",
        )

    log.info(
        "Pattern matching complete",
        {
            "grouped": grouped_count,
            "trackingPatterns": tracking_pattern_hits,
            "trackerDomains": tracker_domain_hits,
            "benignPatterns": benign_pattern_hits,
            "unknown": len(unknown_scripts),
            "total": len(results),
        },
    )

    return unknown_scripts


async def _analyze_unknowns(
    results: list[tracking_data.TrackedScript],
    unknown_scripts: list[tuple[tracking_data.TrackedScript, int]],
    on_progress: ScriptAnalysisProgressCallback | None,
) -> None:
    """Fetch, cache-check, and LLM-analyse unknown scripts.

    Scripts sharing the same base URL (ignoring query strings)
    are deduplicated so that only one fetch and one LLM call is
    made per unique file.  The result is applied to every script
    that shares that base URL.

    The cache is keyed by the **script's own domain** (e.g.
    ``s0.2mdn.net``), not by the site being scanned.  This
    means a Google Ads script analysed during a scan of
    site-A.com is an immediate cache hit when site-B.com
    includes the same script.

    Mutates *results* in-place with descriptions from cache hits
    and LLM analysis.  Saves newly analysed scripts to the
    per-script-domain caches.
    """
    # ── Deduplicate by base URL ────────────────────────────
    base_url_groups: dict[str, list[tuple[tracking_data.TrackedScript, int]]] = {}
    for script, result_index in unknown_scripts:
        base = script_cache.strip_query_string(script.url)
        base_url_groups.setdefault(base, []).append((script, result_index))

    # Pick one representative from each group for fetching.
    unique_scripts: list[tuple[tracking_data.TrackedScript, list[int]]] = []
    for _base, group in base_url_groups.items():
        representative = group[0][0]
        all_indices = [ri for _, ri in group]
        unique_scripts.append((representative, all_indices))

    deduped_count = len(unknown_scripts) - len(unique_scripts)
    total_to_fetch = len(unique_scripts)
    total_to_analyze = len(unknown_scripts)

    # Collect script domains for logging.
    script_domains = {s.domain for s, _ in unknown_scripts if s.domain != "unknown"}

    log.info(
        "Starting LLM analysis of unknown scripts",
        {
            "toAnalyze": total_to_fetch,
            "deduplicatedByBaseUrl": deduped_count,
            "scriptDomains": len(script_domains),
            "total": len(results),
        },
    )

    if on_progress:
        on_progress("fetching", 0, total_to_fetch, f"Fetching {total_to_fetch} script contents...")

    # ── Fetch all unique script contents in parallel ───────
    fetched_count = 0

    async def fetch_one(
        script: tracking_data.TrackedScript,
        http_session: aiohttp.ClientSession,
    ) -> tuple[str, str | None]:
        nonlocal fetched_count
        content = await _fetch_script_content(script.url, http_session)
        fetched_count += 1
        if on_progress and (fetched_count % 5 == 0 or fetched_count == total_to_fetch):
            on_progress(
                "fetching",
                fetched_count,
                total_to_fetch,
                f"Fetched {fetched_count}/{total_to_fetch} scripts...",
            )
        return script.url, content

    async with aiohttp.ClientSession(
        timeout=_FETCH_TIMEOUT,
    ) as http_session:
        script_contents = await asyncio.gather(*(fetch_one(s, http_session) for s, _ in unique_scripts))

    # Build a lookup from base URL → (script_domain, fetch_url, content, result_indices)
    base_to_info: dict[str, tuple[str, str, str | None, list[int]]] = {}
    for i, (script, result_indices) in enumerate(unique_scripts):
        fetch_url, content = script_contents[i]
        base = script_cache.strip_query_string(fetch_url)
        base_to_info[base] = (script.domain, fetch_url, content, result_indices)

    # ── Load caches per script domain ──────────────────────
    cache_entries: dict[str, script_cache.ScriptCacheEntry | None] = {}
    for script_domain in script_domains:
        if script_domain not in cache_entries:
            cache_entries[script_domain] = script_cache.load(script_domain)

    cache_hits: int = 0
    cache_hit_scripts: int = 0
    soft_hits: int = 0
    hash_dedup_hits: int = 0
    bases_needing_llm: dict[str, tuple[str, str, str | None, list[int]]] = {}

    for base, (script_domain, fetch_url, content, result_indices) in base_to_info.items():
        entry = cache_entries.get(script_domain)
        if entry and content:
            content_hash = script_cache.compute_hash(content)
            cached_desc = script_cache.lookup(entry, fetch_url, content_hash)
            if cached_desc:
                cache_hits += 1
                cache_hit_scripts += len(result_indices)
                if entry.modified:
                    soft_hits += 1
                for ri in result_indices:
                    results[ri] = tracking_data.TrackedScript(
                        url=results[ri].url,
                        domain=results[ri].domain,
                        description=cached_desc,
                        resource_type=results[ri].resource_type,
                    )
                continue

        # Cross-domain hash lookup: the same script content
        # may already be described under a different CDN domain.
        if content:
            content_hash = script_cache.compute_hash(content)
            cross_desc = script_cache.lookup_by_hash(cache_entries, content_hash)
            if cross_desc:
                hash_dedup_hits += 1
                cache_hit_scripts += len(result_indices)
                for ri in result_indices:
                    results[ri] = tracking_data.TrackedScript(
                        url=results[ri].url,
                        domain=results[ri].domain,
                        description=cross_desc,
                        resource_type=results[ri].resource_type,
                    )
                continue

        bases_needing_llm[base] = (script_domain, fetch_url, content, result_indices)

    if cache_hits or hash_dedup_hits or bases_needing_llm:
        log.info(
            "Script cache lookup complete",
            {
                "hits": cache_hits,
                "softHits": soft_hits,
                "hashDedupHits": hash_dedup_hits,
                "misses": len(bases_needing_llm),
                "scriptDomainsCached": len(cache_entries),
            },
        )

    # Persist cache entries that had soft hits (hash updates)
    # but have no pending LLM work.  Entries *with* pending
    # LLM work will be saved later by analyze_with_progress().
    domains_needing_llm = {sd for _, (sd, _, _, _) in bases_needing_llm.items()}
    for sd, entry in cache_entries.items():
        if entry and entry.modified and sd not in domains_needing_llm:
            script_cache.save(sd, [], existing=entry)

    llm_to_analyze = len(bases_needing_llm)

    # ── LLM analysis for cache misses ──────────────────────
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    completed_count = cache_hit_scripts

    if on_progress:
        if cache_hits:
            on_progress(
                "analyzing",
                cache_hit_scripts,
                total_to_analyze,
                f"{cache_hit_scripts} from cache, analyzing {llm_to_analyze} with LLM...",
            )
        elif llm_to_analyze:
            on_progress("analyzing", 0, total_to_analyze, f"Analyzing {llm_to_analyze} scripts with LLM...")

    async def analyze_with_progress(
        url: str,
        content: str | None,
        count: int,
        script_domain: str,
        result_indices: list[int],
    ) -> None:
        """Analyse one script, update results, and save to cache immediately."""
        nonlocal completed_count
        async with semaphore:
            _, description = await _analyze_one_with_llm(url, content)

        # Update result entries in-place.
        for ri in result_indices:
            old = results[ri]
            results[ri] = tracking_data.TrackedScript(
                url=old.url,
                domain=old.domain,
                description=description,
                resource_type=old.resource_type,
            )

        # Save to cache immediately so partial progress
        # survives if a later call times out or the process
        # is interrupted.  Skip caching fallback descriptions
        # that came from URL heuristics — they would mask
        # real LLM results once the agent is fixed.
        if content and not is_fallback_description(description):
            new_entry = script_cache.CachedScript(
                url=url,
                content_hash=script_cache.compute_hash(content),
                description=description,
            )
            existing = cache_entries.get(script_domain)
            script_cache.save(script_domain, [new_entry], existing=existing)
            # Update the in-memory entry so subsequent saves
            # for the same domain carry forward this result.
            if existing is None:
                existing = script_cache.ScriptCacheEntry(domain=script_domain)
                cache_entries[script_domain] = existing
            existing.scripts.append(new_entry)

        completed_count += count
        if on_progress:
            on_progress(
                "analyzing",
                completed_count,
                total_to_analyze,
                f"Analyzed {completed_count}/{total_to_analyze} scripts...",
            )

    if bases_needing_llm:
        await asyncio.gather(
            *(
                analyze_with_progress(
                    fetch_url,
                    content,
                    len(result_indices),
                    script_domain,
                    result_indices,
                )
                for _base, (script_domain, fetch_url, content, result_indices) in bases_needing_llm.items()
            )
        )

    if on_progress:
        on_progress("analyzing", total_to_analyze, total_to_analyze, "Script analysis complete...")

    log.success(
        "Script analysis complete",
        {
            "analyzed": llm_to_analyze,
            "cacheHits": cache_hits,
            "deduplicatedByBaseUrl": deduped_count,
            "concurrency": MAX_CONCURRENCY,
            "total": len(results),
        },
    )
