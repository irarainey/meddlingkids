"""
Script analysis service using LLM.
Analyzes JavaScript files to determine their purpose.
Groups similar scripts (like application chunks) to reduce noise.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

import aiohttp

from src.data.loader import get_benign_scripts, get_tracking_scripts
from src.services.openai_client import get_deployment_name, get_openai_client
from src.types.tracking import ScriptGroup, TrackedScript
from src.utils.errors import get_error_message
from src.utils.logger import create_logger
from src.utils.retry import with_retry

log = create_logger("Script-Analysis")

MIN_GROUP_SIZE = 3
MAX_BATCH_SIZE = 15
MAX_BATCH_CONTENT_LENGTH = 75000
MAX_SCRIPT_CONTENT_LENGTH = 2000

BATCH_SCRIPT_ANALYSIS_PROMPT = """You are a web security analyst. Analyze each script URL and briefly describe its purpose.

For each script, provide a SHORT description (max 10 words) of what the script does.
Focus on: tracking, analytics, advertising, functionality, UI framework, etc.

Return a JSON array with objects containing "url" and "description" for each script.
Example: [{"url": "https://example.com/script.js", "description": "User analytics tracking"}]

Return ONLY the JSON array, no other text."""


# ============================================================================
# Known script identification
# ============================================================================

def _identify_tracking_script(url: str) -> str | None:
    """Check if a script is a known tracking script."""
    for entry in get_tracking_scripts():
        if re.search(entry.pattern, url, re.IGNORECASE):
            return entry.description
    return None


def _identify_benign_script(url: str) -> str | None:
    """Check if a script is a known benign script (skip LLM analysis)."""
    for entry in get_benign_scripts():
        if re.search(entry.pattern, url, re.IGNORECASE):
            return entry.description
    return None


# ============================================================================
# Content fetching
# ============================================================================

async def _fetch_script_content(url: str, retries: int = 2) -> str | None:
    """Fetch a script's content for analysis with retry."""
    for attempt in range(retries + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {"User-Agent": "Mozilla/5.0 (compatible; SecurityAnalyzer/1.0)"}
                async with session.get(url, headers=headers) as response:
                    if response.status >= 400:
                        if attempt < retries and (response.status >= 500 or response.status == 429):
                            import asyncio
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                        return None
                    return await response.text()
        except Exception:
            if attempt < retries:
                import asyncio
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            return None
    return None


# ============================================================================
# LLM batch analysis
# ============================================================================

async def _analyze_batch_with_llm(
    scripts: list[dict[str, str | None]],
) -> dict[str, str]:
    """Analyze multiple scripts in a single LLM batch call."""
    client = get_openai_client()
    results: dict[str, str] = {}

    if not client or not scripts:
        return results

    deployment = get_deployment_name()

    batch_content = "\n".join(
        f"Script {i + 1}: {s['url']}\n{(s['content'] or '[Content not available]')[:MAX_SCRIPT_CONTENT_LENGTH]}\n---"
        for i, s in enumerate(scripts)
    )

    try:
        log.debug("Sending batch to LLM", {"scriptCount": len(scripts)})

        response = await with_retry(
            lambda: client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": BATCH_SCRIPT_ANALYSIS_PROMPT},
                    {"role": "user", "content": f"Analyze these {len(scripts)} scripts:\n\n{batch_content}"},
                ],
                max_completion_tokens=1000,
            ),
            context=f"Batch script analysis ({len(scripts)} scripts)",
            max_retries=2,
        )

        content = response.choices[0].message.content or "[]"
        json_str = content.strip()
        if json_str.startswith("```"):
            json_str = re.sub(r"```json?\n?", "", json_str)
            json_str = re.sub(r"```$", "", json_str).strip()

        parsed = json.loads(json_str)
        for item in parsed:
            if item.get("url") and item.get("description"):
                results[item["url"]] = item["description"]

        log.debug("Batch analysis complete", {"received": len(results), "expected": len(scripts)})
    except Exception as error:
        log.error("Batch script analysis failed", {"error": get_error_message(error)})
        for script in scripts:
            url = script.get("url", "")
            if url:
                results[url] = _infer_from_url(url)

    return results


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


# ============================================================================
# Grouping
# ============================================================================

@dataclass
class GroupPattern:
    id: str
    name: str
    description: str
    pattern: re.Pattern[str]


GROUPABLE_PATTERNS: list[GroupPattern] = [
    GroupPattern(
        id="app-chunks",
        name="Application code chunks",
        description="Code-split application bundles (SPA framework chunks)",
        pattern=re.compile(
            r"(?:chunk|_app|_next|main|page|pages)[-._]?[a-f0-9]{5,}\.js|"
            r"[a-f0-9]{8,}\.(?:chunk|module)\.js|\d+\.[a-f0-9]{6,}\.js|"
            r"chunks?/[^/]+\.js|_next/static/chunks",
            re.I,
        ),
    ),
    GroupPattern(
        id="vendor-bundles",
        name="Vendor bundles",
        description="Third-party library bundles (node_modules)",
        pattern=re.compile(
            r"(?:vendor|vendors|framework|commons|shared|lib)[-._~][a-f0-9]*\.js|node_modules.*\.js",
            re.I,
        ),
    ),
    GroupPattern(
        id="webpack-runtime",
        name="Webpack runtime",
        description="Webpack module loading runtime",
        pattern=re.compile(
            r"webpack[-._]?runtime[-._]?[a-f0-9]*\.js|runtime[-~][a-f0-9]+\.js|__webpack_require__",
            re.I,
        ),
    ),
    GroupPattern(
        id="lazy-modules",
        name="Lazy-loaded modules",
        description="Dynamically imported modules",
        pattern=re.compile(
            r"(?:lazy|async|dynamic)[-._]?[a-f0-9]+\.js|/\d{1,4}\.[a-f0-9]{6,}\.js$",
            re.I,
        ),
    ),
    GroupPattern(
        id="css-chunks",
        name="CSS-in-JS chunks",
        description="Styled component or CSS module chunks",
        pattern=re.compile(r"styles?[-._]?[a-f0-9]+\.js|css[-._]?[a-f0-9]+\.js", re.I),
    ),
    GroupPattern(
        id="polyfills",
        name="Polyfill bundles",
        description="Browser compatibility polyfills",
        pattern=re.compile(r"polyfill[s]?[-._]?[a-f0-9]*\.js|core-js.*\.js", re.I),
    ),
    GroupPattern(
        id="static-assets",
        name="Static asset scripts",
        description="Hashed static JavaScript files",
        pattern=re.compile(
            r"/static/(?:js|chunks?)/[^/]+\.[a-f0-9]{8,}\.js|/assets/[^/]+\.[a-f0-9]{8,}\.js",
            re.I,
        ),
    ),
]


def _get_groupable_pattern(url: str) -> GroupPattern | None:
    for gp in GROUPABLE_PATTERNS:
        if gp.pattern.search(url):
            return gp
    return None


@dataclass
class GroupedScriptsResult:
    individual_scripts: list[TrackedScript] = field(default_factory=list)
    groups: list[ScriptGroup] = field(default_factory=list)
    all_scripts: list[TrackedScript] = field(default_factory=list)


def group_similar_scripts(scripts: list[TrackedScript]) -> GroupedScriptsResult:
    """Group similar scripts together to reduce noise."""
    domain_groups: dict[str, dict[str, list[TrackedScript]]] = {}
    individual_scripts: list[TrackedScript] = []
    all_scripts: list[TrackedScript] = []

    for script in scripts:
        gp = _get_groupable_pattern(script.url)
        if gp:
            key = f"{script.domain}:{gp.id}"
            if key not in domain_groups:
                domain_groups[key] = {}
            if gp.id not in domain_groups[key]:
                domain_groups[key][gp.id] = []
            domain_groups[key][gp.id].append(script)
        else:
            individual_scripts.append(script)
            all_scripts.append(script)

    groups: list[ScriptGroup] = []
    for key, pattern_map in domain_groups.items():
        domain, pattern_id = key.split(":", 1)
        pattern_info = next((p for p in GROUPABLE_PATTERNS if p.id == pattern_id), None)

        for _, scripts_in_group in pattern_map.items():
            if len(scripts_in_group) >= MIN_GROUP_SIZE and pattern_info:
                group_id = f"{domain}-{pattern_id}"
                groups.append(ScriptGroup(
                    id=group_id,
                    name=pattern_info.name,
                    description=f"{len(scripts_in_group)} {pattern_info.description.lower()}",
                    count=len(scripts_in_group),
                    example_urls=[s.url for s in scripts_in_group[:3]],
                    domain=domain,
                ))
                for s in scripts_in_group:
                    all_scripts.append(TrackedScript(
                        url=s.url,
                        domain=s.domain,
                        description=pattern_info.description,
                        group_id=group_id,
                        is_grouped=True,
                        resource_type=s.resource_type,
                    ))
            else:
                for s in scripts_in_group:
                    individual_scripts.append(s)
                    all_scripts.append(s)

    log.info("Script grouping complete", {
        "total": len(scripts),
        "individual": len(individual_scripts),
        "groups": len(groups),
        "grouped": sum(1 for s in all_scripts if s.is_grouped),
    })

    return GroupedScriptsResult(
        individual_scripts=individual_scripts,
        groups=groups,
        all_scripts=all_scripts,
    )


# Type alias for progress callback
ScriptAnalysisProgressCallback = Callable[[str, int, int, str], None]


@dataclass
class ScriptAnalysisResult:
    scripts: list[TrackedScript] = field(default_factory=list)
    groups: list[ScriptGroup] = field(default_factory=list)


async def analyze_scripts(
    scripts: list[TrackedScript],
    on_progress: ScriptAnalysisProgressCallback | None = None,
) -> ScriptAnalysisResult:
    """
    Analyze multiple scripts to determine their purposes.

    Process:
    1. Group similar scripts (chunks, vendor bundles) — skip LLM analysis
    2. Match remaining against known patterns (tracking + benign)
    3. Send only truly unknown scripts to LLM for batch analysis
    """
    import asyncio

    grouped = group_similar_scripts(scripts)
    results: list[TrackedScript] = list(grouped.all_scripts)
    unknown_scripts: list[tuple[TrackedScript, int]] = []

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
            results[i] = TrackedScript(
                url=script.url, domain=script.domain, description=tracking_desc,
                resource_type=script.resource_type,
            )
            continue

        benign_desc = _identify_benign_script(script.url)
        if benign_desc:
            results[i] = TrackedScript(
                url=script.url, domain=script.domain, description=benign_desc,
                resource_type=script.resource_type,
            )
            continue

        results[i] = TrackedScript(
            url=script.url, domain=script.domain, description="Analyzing...",
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
        log.info("Starting LLM analysis of unknown scripts", {
            "toAnalyze": total_to_analyze,
            "grouped": grouped_count,
            "knownCount": known_count,
            "total": len(scripts),
        })

        if on_progress:
            on_progress("fetching", 0, total_to_analyze, f"Fetching {total_to_analyze} script contents...")

        # Fetch all script contents in parallel
        fetched_count = 0

        async def fetch_one(script: TrackedScript) -> dict[str, str | None]:
            nonlocal fetched_count
            content = await _fetch_script_content(script.url)
            fetched_count += 1
            if on_progress and (fetched_count % 5 == 0 or fetched_count == total_to_analyze):
                on_progress("fetching", fetched_count, total_to_analyze, f"Fetched {fetched_count}/{total_to_analyze} scripts...")
            return {"url": script.url, "content": content}

        script_contents = await asyncio.gather(*(fetch_one(s) for s, _ in unknown_scripts))

        # Create batches
        batches: list[list[tuple[dict[str, str | None], int]]] = []
        current_batch: list[tuple[dict[str, str | None], int]] = []
        current_content_len = 0

        for i_idx, (script, result_index) in enumerate(unknown_scripts):
            content_entry = script_contents[i_idx]
            content_len = len(content_entry.get("content") or "")

            if (
                len(current_batch) >= MAX_BATCH_SIZE
                or (current_content_len + content_len > MAX_BATCH_CONTENT_LENGTH and current_batch)
            ):
                batches.append(current_batch)
                current_batch = []
                current_content_len = 0

            current_batch.append((content_entry, result_index))
            current_content_len += content_len

        if current_batch:
            batches.append(current_batch)

        log.info("Processing scripts in batches", {"batches": len(batches), "totalScripts": total_to_analyze})

        if on_progress:
            on_progress("analyzing", 0, total_to_analyze, f"Analyzing {total_to_analyze} unknown scripts in {len(batches)} batches...")

        completed_count = 0
        for batch_idx, batch in enumerate(batches):
            if on_progress:
                on_progress(
                    "analyzing", completed_count, total_to_analyze,
                    f"Analyzing unknown script batch {batch_idx + 1} of {len(batches)}...",
                )

            batch_results = await _analyze_batch_with_llm(
                [{"url": entry["url"], "content": entry.get("content")} for entry, _ in batch]
            )

            for entry, result_index in batch:
                url = entry["url"] or ""
                description = batch_results.get(url, _infer_from_url(url))
                old = results[result_index]
                results[result_index] = TrackedScript(
                    url=old.url, domain=old.domain, description=description,
                    resource_type=old.resource_type,
                )
                completed_count += 1

            if on_progress:
                on_progress(
                    "analyzing", completed_count, total_to_analyze,
                    f"Completed batch {batch_idx + 1} of {len(batches)} ({completed_count}/{total_to_analyze} scripts)",
                )

        if on_progress:
            on_progress("analyzing", total_to_analyze, total_to_analyze, "Script analysis complete")

        log.success("Script analysis complete", {
            "analyzed": completed_count,
            "batches": len(batches),
            "grouped": grouped_count,
            "total": len(results),
        })
    else:
        log.info("All scripts identified from patterns or grouped, no LLM analysis needed")
        if on_progress:
            on_progress("analyzing", 0, 0, "All scripts identified from patterns or grouped")

    return ScriptAnalysisResult(scripts=results, groups=grouped.groups)
