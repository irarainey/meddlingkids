"""Domain-level knowledge cache for analysis consistency.

Stores LLM-generated classifications (tracker categories,
cookie groupings, vendor roles, severity assignments) from
a previous analysis of the same domain.  When a subsequent
scan runs against the same domain, these prior findings are
injected into the LLM context as anchoring guidance so that
the model produces consistent labels across runs.

Cache files are JSON stored under ``server/.cache/domain/``.
Each file is named by the base domain (``www.`` stripped).

**Merge behaviour:** On each successful analysis the new
findings are *merged* with the existing cache rather than
overwriting it.  Items present in the latest report have
their ``last_seen_scan`` updated to the current scan count.
Items from prior scans that are no longer present are kept
for up to ``_STALE_SCAN_THRESHOLD`` scans and then pruned
automatically, preventing transient/A-B-test entries from
disappearing after a single run.
"""

from __future__ import annotations

import json
import pathlib
import re
from collections.abc import Callable

import pydantic

from src.models import report
from src.utils import logger

log = logger.create_logger("DomainCache")

# Cache directory — lives alongside server source, gitignored.
_CACHE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / ".cache" / "domain"

# Items not seen for this many consecutive scans are pruned.
_STALE_SCAN_THRESHOLD = 3


# ── Cached classification models ───────────────────────────────


class CachedTracker(pydantic.BaseModel):
    """A previously classified tracker."""

    name: str
    category: str  # analytics, advertising, etc.
    purpose: str
    last_seen_scan: int = 0


class CachedCookieGroup(pydantic.BaseModel):
    """A previously classified cookie group."""

    category: str
    cookies: list[str]
    concern_level: str
    last_seen_scan: int = 0


class CachedVendor(pydantic.BaseModel):
    """A previously classified vendor."""

    name: str
    role: str
    last_seen_scan: int = 0


class CachedDataCategory(pydantic.BaseModel):
    """A previously used data collection category."""

    category: str
    risk: str
    sensitive: bool = False
    last_seen_scan: int = 0


class DomainKnowledge(pydantic.BaseModel):
    """Cached knowledge about a domain from prior analyses.

    Contains the stable classifications that should remain
    consistent across runs of the same domain.  ``scan_count``
    is incremented on each successful analysis so that stale
    items can be aged out after ``_STALE_SCAN_THRESHOLD`` scans
    without being seen again.
    """

    domain: str
    scan_count: int = 0
    trackers: list[CachedTracker] = pydantic.Field(default_factory=list)
    cookie_groups: list[CachedCookieGroup] = pydantic.Field(default_factory=list)
    vendors: list[CachedVendor] = pydantic.Field(default_factory=list)
    data_categories: list[CachedDataCategory] = pydantic.Field(default_factory=list)


# ── File helpers ────────────────────────────────────────────────


def _domain_path(domain: str) -> pathlib.Path:
    """Build the cache file path for a domain.

    Strips ``www.`` prefix so ``www.example.com`` and
    ``example.com`` share the same cache entry.
    """
    safe = domain.lower().removeprefix("www.")
    safe = "".join(c if c.isalnum() or c in ".-" else "_" for c in safe)[:100]
    return _CACHE_DIR / f"{safe}.json"


# ── Public API ──────────────────────────────────────────────────


def load(domain: str) -> DomainKnowledge | None:
    """Load cached domain knowledge.

    Returns ``None`` when no cache exists or the file is
    malformed.
    """
    path = _domain_path(domain)
    if not path.exists():
        log.debug("No domain cache", {"domain": domain})
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = DomainKnowledge.model_validate(data)
        log.info(
            "Domain cache loaded",
            {
                "domain": domain,
                "trackers": len(entry.trackers),
                "cookieGroups": len(entry.cookie_groups),
                "vendors": len(entry.vendors),
            },
        )
        return entry
    except Exception as exc:
        log.warn(
            "Failed to read domain cache, removing",
            {"domain": domain, "error": str(exc)},
        )
        _remove(path)
        return None


def save_from_report(
    domain: str,
    structured_report: report.StructuredReport,
) -> None:
    """Extract classifications from a report and merge with the cache.

    Rather than overwriting the entire cache, this function:

    1. Loads the existing cache (if any).
    2. Increments ``scan_count``.
    3. Merges each classification list — items present in the
       latest report are updated with the new labels and their
       ``last_seen_scan`` is set to the current count.  Items
       from prior scans that are **not** in the latest report
       are carried forward unchanged.
    4. Prunes items whose ``last_seen_scan`` is more than
       ``_STALE_SCAN_THRESHOLD`` scans old.
    5. Writes the merged result to disk.
    """
    existing = load(domain)
    scan_count = (existing.scan_count if existing else 0) + 1

    new_trackers = _extract_trackers(structured_report.tracking_technologies, scan_count)
    new_cookie_groups = _extract_cookie_groups(structured_report.cookie_analysis, scan_count)
    new_vendors = _extract_vendors(structured_report.key_vendors, scan_count)
    new_data_categories = _extract_data_categories(structured_report.data_collection, scan_count)

    merged_trackers = _merge_by_name(
        old=existing.trackers if existing else [],
        new=new_trackers,
        name_attr="name",
    )
    merged_cookie_groups = _merge_by_key(
        old=existing.cookie_groups if existing else [],
        new=new_cookie_groups,
        key=lambda g: g.category.lower(),
    )
    merged_vendors = _merge_by_name(
        old=existing.vendors if existing else [],
        new=new_vendors,
        name_attr="name",
    )
    merged_data_categories = _merge_by_key(
        old=existing.data_categories if existing else [],
        new=new_data_categories,
        key=lambda d: d.category.lower(),
    )

    entry = DomainKnowledge(
        domain=domain,
        scan_count=scan_count,
        trackers=_prune_stale(merged_trackers, scan_count),
        cookie_groups=_prune_stale(merged_cookie_groups, scan_count),
        vendors=_prune_stale(merged_vendors, scan_count),
        data_categories=_prune_stale(merged_data_categories, scan_count),
    )

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _domain_path(domain)
    try:
        path.write_text(entry.model_dump_json(indent=2), encoding="utf-8")
        log.info(
            "Domain cache saved",
            {
                "domain": domain,
                "scanCount": scan_count,
                "trackers": len(entry.trackers),
                "cookieGroups": len(entry.cookie_groups),
                "vendors": len(entry.vendors),
                "path": str(path.name),
            },
        )
    except Exception as exc:
        log.warn(
            "Failed to write domain cache",
            {"domain": domain, "error": str(exc)},
        )


def build_context_hint(knowledge: DomainKnowledge) -> str:
    """Format cached knowledge as a context block for LLM prompts.

    Returns a markdown section that can be appended to the
    data context string so the LLM anchors its classifications
    to the previously established labels.
    """
    lines: list[str] = [
        "",
        "## Previous Analysis Context (use for consistency)",
        "The following classifications were established in a "
        "prior analysis of this domain. Reuse the SAME category "
        "names, severity levels, and vendor roles unless the "
        "underlying data has materially changed.",
        "",
        "**Naming rule:** Use the SHORT canonical company name "
        "listed below. Do NOT add parenthetical aliases, alternate "
        "product names, or role qualifiers to tracker or vendor "
        "names. If the same company appears under multiple names "
        "in the data, use the single name shown here.",
        "",
    ]

    if knowledge.trackers:
        lines.append("### Known Trackers")
        for t in knowledge.trackers:
            lines.append(f"- {t.name} [{t.category}]: {t.purpose}")
        lines.append("")

    if knowledge.cookie_groups:
        lines.append("### Cookie Classifications")
        for g in knowledge.cookie_groups:
            lines.append(f"- {g.category} ({g.concern_level}): {', '.join(g.cookies[:10])}")
        lines.append("")

    if knowledge.data_categories:
        lines.append("### Data Collection Categories")
        for d in knowledge.data_categories:
            sens = " [SENSITIVE]" if d.sensitive else ""
            lines.append(f"- {d.category} ({d.risk}){sens}")
        lines.append("")

    if knowledge.vendors:
        lines.append("### Known Vendors")
        for v in knowledge.vendors:
            lines.append(f"- {v.name}: {v.role}")
        lines.append("")

    return "\n".join(lines)


# ── Merge & prune helpers ───────────────────────────────────────

type _T = CachedTracker | CachedCookieGroup | CachedVendor | CachedDataCategory

# Parenthetical qualifiers the LLM adds inconsistently,
# e.g. "Scorecard Research (Comscore)" vs "Comscore (Scorecard Research)".
_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*")
# Common filler words that vary across runs.
_FILLER_RE = re.compile(r"\b(components?|services?|identity|internal)\b", re.IGNORECASE)
# Collapse whitespace / punctuation noise.
_WS_RE = re.compile(r"[\s\-_/&,]+")


def _normalize_name(name: str) -> str:
    """Reduce a tracker/vendor name to a stable merge key.

    Strips parenthetical qualifiers, filler words, and
    punctuation so that "Scorecard Research (Comscore)",
    "Comscore (Scorecard Research)", and "Comscore" all
    map to keys that :func:`_names_match` considers equal.
    Returns sorted, lowered tokens joined by spaces.
    """
    s = _PAREN_RE.sub(" ", name)
    s = _FILLER_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip().lower()
    tokens = sorted(set(s.split()))
    return " ".join(tokens)


def _extract_paren_tokens(name: str) -> set[str]:
    """Return lowered tokens from parenthetical qualifiers.

    For "Scorecard Research (Comscore)" returns ``{"comscore"}``.
    """
    tokens: set[str] = set()
    for m in _PAREN_RE.finditer(name):
        inner = m.group().strip("() \t")
        inner = _WS_RE.sub(" ", inner).strip().lower()
        tokens.update(inner.split())
    return tokens


def _names_match(a: str, b: str, raw_a: str = "", raw_b: str = "") -> bool:
    """Return True if two normalized names refer to the same entity.

    Matches when:
    - The normalized keys are identical, OR
    - One is a subset of the other's tokens, OR
    - A parenthetical qualifier in one name matches the
      other's main tokens (e.g. "Scorecard Research (Comscore)"
      matches "Comscore").
    """
    if a == b:
        return True

    a_tokens = set(a.split())
    b_tokens = set(b.split())

    # One name's tokens are a subset of the other's.
    if a_tokens <= b_tokens or b_tokens <= a_tokens:
        return True

    # Check parenthetical cross-match.
    if raw_a and raw_b:
        paren_a = _extract_paren_tokens(raw_a)
        paren_b = _extract_paren_tokens(raw_b)
        # "Scorecard Research (Comscore)" vs "Comscore":
        # paren_a = {"comscore"}, b_tokens = {"comscore"} → match
        if paren_a and paren_a & b_tokens:
            return True
        if paren_b and paren_b & a_tokens:
            return True

    return False


def _merge_by_key[T: _T](
    old: list[T],
    new: list[T],
    key: Callable[[T], str],
) -> list[T]:
    """Merge two lists by a key function.

    Items present in *new* replace same-key items in *old*.
    Items only in *old* are carried forward with their
    existing ``last_seen_scan`` value so they can be aged out.
    Ordering: new items first (report order), then carried-
    forward old items.
    """
    new_index: dict[str, T] = {}
    for item in new:
        k = key(item)
        if k not in new_index:
            new_index[k] = item

    result = list(new_index.values())

    for item in old:
        if key(item) not in new_index:
            result.append(item)

    return result


def _merge_by_name[T: (CachedTracker, CachedVendor)](
    old: list[T],
    new: list[T],
    name_attr: str = "name",
) -> list[T]:
    """Merge two lists with fuzzy name matching.

    Uses :func:`_names_match` to detect near-duplicates like
    "Comscore" vs "Scorecard Research (Comscore)".  New items
    replace fuzzy-matched old items.
    """
    # Build new index, deduplicating with fuzzy matching.
    new_items: list[tuple[str, str, T]] = []
    for item in new:
        raw = getattr(item, name_attr)
        norm = _normalize_name(raw)
        # Check if this item fuzzy-matches any already-accepted item.
        already_present = False
        for existing_norm, existing_raw, _ in new_items:
            if _names_match(norm, existing_norm, raw, existing_raw):
                already_present = True
                break
        if not already_present:
            new_items.append((norm, raw, item))

    result = [item for _, _, item in new_items]

    for old_item in old:
        old_raw = getattr(old_item, name_attr)
        old_norm = _normalize_name(old_raw)
        matched = False
        for new_norm, new_raw, _ in new_items:
            if _names_match(old_norm, new_norm, old_raw, new_raw):
                matched = True
                break
        if not matched:
            result.append(old_item)

    return result


def _prune_stale[T: _T](items: list[T], current_scan: int) -> list[T]:
    """Remove items not seen in the last N scans."""
    kept: list[T] = []
    for item in items:
        age = current_scan - item.last_seen_scan
        if age <= _STALE_SCAN_THRESHOLD:
            kept.append(item)
        else:
            log.debug(
                "Pruning stale cache entry",
                {"item": getattr(item, "name", None) or getattr(item, "category", "?"), "age": age},
            )
    return kept


# ── Extraction helpers ──────────────────────────────────────────


def _extract_trackers(
    tech: report.TrackingTechnologiesSection,
    scan_count: int,
) -> list[CachedTracker]:
    """Pull tracker names and categories from the report.

    Deduplicates within a single report by normalized name
    so near-duplicates like "Comscore" and "Scorecard Research
    (Comscore)" collapse to the first occurrence.
    """
    seen: set[str] = set()
    result: list[CachedTracker] = []
    for cat_name, cat_list in [
        ("analytics", tech.analytics),
        ("advertising", tech.advertising),
        ("identity_resolution", tech.identity_resolution),
        ("social_media", tech.social_media),
        ("other", tech.other),
    ]:
        for tracker in cat_list:
            key = _normalize_name(tracker.name)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                CachedTracker(
                    name=tracker.name,
                    category=cat_name,
                    purpose=tracker.purpose,
                    last_seen_scan=scan_count,
                )
            )
    return result


def _extract_cookie_groups(
    cookies: report.CookieAnalysisSection,
    scan_count: int,
) -> list[CachedCookieGroup]:
    """Pull cookie groupings from the report."""
    return [
        CachedCookieGroup(
            category=g.category,
            cookies=g.cookies,
            concern_level=g.concern_level,
            last_seen_scan=scan_count,
        )
        for g in cookies.groups
    ]


def _extract_vendors(
    vendors: report.VendorSection,
    scan_count: int,
) -> list[CachedVendor]:
    """Pull vendor names and roles from the report.

    Deduplicates by normalized name within a single report.
    """
    seen: set[str] = set()
    result: list[CachedVendor] = []
    for v in vendors.vendors:
        key = _normalize_name(v.name)
        if key in seen:
            continue
        seen.add(key)
        result.append(CachedVendor(name=v.name, role=v.role, last_seen_scan=scan_count))
    return result


def _extract_data_categories(
    data: report.DataCollectionSection,
    scan_count: int,
) -> list[CachedDataCategory]:
    """Pull data collection categories from the report."""
    return [
        CachedDataCategory(
            category=item.category,
            risk=item.risk,
            sensitive=item.sensitive,
            last_seen_scan=scan_count,
        )
        for item in data.items
    ]


def _remove(path: pathlib.Path) -> None:
    """Delete a cache file, logging the outcome."""
    if path.exists():
        try:
            path.unlink()
            log.info("Domain cache removed", {"path": str(path.name)})
        except Exception as exc:
            log.warn(
                "Failed to remove domain cache",
                {"path": str(path.name), "error": str(exc)},
            )
