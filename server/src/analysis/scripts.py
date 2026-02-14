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


# ============================================================================
# Content fetching
# ============================================================================

_FETCH_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SecurityAnalyzer/1.0)"}
_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=5)


async def _fetch_script_content(
    url: str,
    http_session: aiohttp.ClientSession,
    retries: int = 2,
) -> str | None:
    """Fetch a script's content for analysis with retry.

    Accepts a shared ``aiohttp.ClientSession`` so that TCP
    connections are reused across many concurrent fetches.
    """
    for attempt in range(retries + 1):
        try:
            async with http_session.get(url, headers=_FETCH_HEADERS) as response:
                if response.status >= 400:
                    if attempt < retries and (response.status >= 500 or response.status == 429):
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    log.debug("Script fetch failed", {"url": url, "status": response.status})
                    return None
                return await response.text()
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


# Type alias for progress callback
ScriptAnalysisProgressCallback = Callable[[str, int, int, str], None]


class ScriptAnalysisResult(pydantic.BaseModel):
    """Result of analyzing a set of scripts."""

    scripts: list[tracking_data.TrackedScript] = pydantic.Field(default_factory=list)
    groups: list[tracking_data.ScriptGroup] = pydantic.Field(default_factory=list)


async def analyze_scripts(
    scripts: list[tracking_data.TrackedScript],
    on_progress: ScriptAnalysisProgressCallback | None = None,
    *,
    domain: str = "",
) -> ScriptAnalysisResult:
    """
    Analyze multiple scripts to determine their purposes.

    Process:
    1. Group similar scripts (chunks, vendor bundles) — skip LLM analysis
    2. Match remaining against known patterns (tracking + benign)
    3. Check the per-domain script cache for previously analysed scripts
    4. Send only uncached unknown scripts to the LLM agent concurrently
    5. Save newly analysed scripts to the cache
    """
    grouped = script_grouping.group_similar_scripts(scripts)
    results: list[tracking_data.TrackedScript] = list(grouped.all_scripts)
    unknown_scripts: list[tuple[tracking_data.TrackedScript, int]] = []

    grouped_count = sum(1 for s in grouped.all_scripts if s.is_grouped)

    if on_progress:
        detail = (
            f"Grouped {grouped_count} similar scripts, matching {len(grouped.individual_scripts)} against known patterns..."
            if grouped_count > 0
            else "Matching scripts against known patterns..."
        )
        on_progress("matching", 0, len(grouped.individual_scripts), detail)

    # Match non-grouped scripts against known patterns
    for i, script in enumerate(results):
        if script.is_grouped:
            continue

        tracking_desc = _identify_tracking_script(script.url)
        if tracking_desc:
            results[i] = tracking_data.TrackedScript(
                url=script.url,
                domain=script.domain,
                description=tracking_desc,
                resource_type=script.resource_type,
            )
            continue

        benign_desc = _identify_benign_script(script.url)
        if benign_desc:
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

    known_count = len(grouped.individual_scripts) - len(unknown_scripts)
    if on_progress:
        on_progress(
            "matching",
            len(grouped.individual_scripts),
            len(grouped.individual_scripts),
            f"Grouped {grouped_count} scripts, identified {known_count} known, {len(unknown_scripts)} unknown",
        )

    total_to_analyze = len(unknown_scripts)

    if unknown_scripts:
        log.info(
            "Starting LLM analysis of unknown scripts",
            {
                "toAnalyze": total_to_analyze,
                "grouped": grouped_count,
                "knownCount": known_count,
                "total": len(scripts),
            },
        )

        if on_progress:
            on_progress("fetching", 0, total_to_analyze, f"Fetching {total_to_analyze} script contents...")

        # Fetch all script contents in parallel using a shared session
        fetched_count = 0

        async def fetch_one(
            script: tracking_data.TrackedScript,
            http_session: aiohttp.ClientSession,
        ) -> tuple[str, str | None]:
            nonlocal fetched_count
            content = await _fetch_script_content(script.url, http_session)
            fetched_count += 1
            if on_progress and (fetched_count % 5 == 0 or fetched_count == total_to_analyze):
                on_progress(
                    "fetching",
                    fetched_count,
                    total_to_analyze,
                    f"Fetched {fetched_count}/{total_to_analyze} scripts...",
                )
            return script.url, content

        async with aiohttp.ClientSession(timeout=_FETCH_TIMEOUT) as http_session:
            script_contents = await asyncio.gather(*(fetch_one(s, http_session) for s, _ in unknown_scripts))

        # Build a lookup from URL → (content, result_index)
        url_to_info: dict[str, tuple[str | None, int]] = {}
        for i, (_, result_index) in enumerate(unknown_scripts):
            url, content = script_contents[i]
            url_to_info[url] = (content, result_index)

        # ── Script cache lookup ────────────────────────────────
        # Check cached descriptions before hitting the LLM.
        cache_entry = script_cache.load(domain) if domain else None
        cache_hits: int = 0
        newly_analyzed: list[script_cache.CachedScript] = []
        urls_needing_llm: dict[str, tuple[str | None, int]] = {}

        for url, (content, result_index) in url_to_info.items():
            if cache_entry and content:
                content_hash = script_cache.compute_hash(content)
                cached_desc = script_cache.lookup(cache_entry, url, content_hash)
                if cached_desc:
                    cache_hits += 1
                    results[result_index] = tracking_data.TrackedScript(
                        url=results[result_index].url,
                        domain=results[result_index].domain,
                        description=cached_desc,
                        resource_type=results[result_index].resource_type,
                    )
                    # Carry the hit forward so it's preserved on save.
                    newly_analyzed.append(script_cache.CachedScript(url=url, content_hash=content_hash, description=cached_desc))
                    continue
            urls_needing_llm[url] = (content, result_index)

        if cache_hits or urls_needing_llm:
            log.info(
                "Script cache lookup complete",
                {"hits": cache_hits, "misses": len(urls_needing_llm), "domain": domain},
            )

        llm_to_analyze = len(urls_needing_llm)

        # ── LLM analysis for cache misses ──────────────────────
        # Analyse each script concurrently with a semaphore to
        # avoid overwhelming the LLM endpoint with too many
        # parallel requests.
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        completed_count = cache_hits

        if on_progress:
            if cache_hits:
                on_progress(
                    "analyzing",
                    cache_hits,
                    total_to_analyze,
                    f"{cache_hits} cached, analyzing {llm_to_analyze} unknown scripts...",
                )
            else:
                on_progress("analyzing", 0, total_to_analyze, f"Analyzing {total_to_analyze} unknown scripts...")

        async def analyze_with_progress(url: str, content: str | None) -> tuple[str, str]:
            nonlocal completed_count
            async with semaphore:
                result = await _analyze_one_with_llm(url, content)
            completed_count += 1
            if on_progress:
                on_progress(
                    "analyzing",
                    completed_count,
                    total_to_analyze,
                    f"Analyzed {completed_count}/{total_to_analyze} scripts...",
                )
            return result

        if urls_needing_llm:
            llm_results = await asyncio.gather(*(analyze_with_progress(url, content) for url, (content, _) in urls_needing_llm.items()))

            # Write descriptions back into the results list and
            # collect entries for the script cache.
            for url, description in llm_results:
                content, result_index = urls_needing_llm[url]
                old = results[result_index]
                results[result_index] = tracking_data.TrackedScript(
                    url=old.url,
                    domain=old.domain,
                    description=description,
                    resource_type=old.resource_type,
                )
                if content:
                    newly_analyzed.append(
                        script_cache.CachedScript(
                            url=url,
                            content_hash=script_cache.compute_hash(content),
                            description=description,
                        )
                    )

        # ── Save script cache ──────────────────────────────────
        if domain and newly_analyzed:
            script_cache.save(domain, newly_analyzed, existing=cache_entry)

        if on_progress:
            on_progress("analyzing", total_to_analyze, total_to_analyze, "Script analysis complete...")

        log.success(
            "Script analysis complete",
            {
                "analyzed": llm_to_analyze,
                "cacheHits": cache_hits,
                "concurrency": MAX_CONCURRENCY,
                "grouped": grouped_count,
                "total": len(results),
            },
        )
    else:
        log.info("All scripts identified from patterns or grouped, no LLM analysis needed")
        if on_progress:
            on_progress("analyzing", 0, 0, "All scripts identified from patterns or grouped")

    return ScriptAnalysisResult(scripts=results, groups=grouped.groups)
