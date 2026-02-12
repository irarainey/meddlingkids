"""
Script grouping — collapse similar scripts (chunks, vendor bundles, etc.) into logical groups.

Reduces noise by recognising common build-tool output patterns so the
analyser can focus on genuinely interesting scripts.
"""

from __future__ import annotations

import re

import pydantic

from src.models import tracking_data
from src.utils import logger

log = logger.create_logger("Script-Grouping")

# Minimum number of scripts matching a pattern before they
# are collapsed into a named group.  Kept at 2 to avoid the
# "threshold edge effect" where the same site oscillates
# between 2 (individual → unknown) and 3+ (grouped → known)
# across runs due to timing-dependent lazy loads.
MIN_GROUP_SIZE = 2


# ---------------------------------------------------------------------------
# Groupable patterns
# ---------------------------------------------------------------------------


class GroupPattern(pydantic.BaseModel):
    """Pattern definition for matching groups of related scripts."""

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

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


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class GroupedScriptsResult(pydantic.BaseModel):
    """Result of grouping similar scripts together."""

    individual_scripts: list[tracking_data.TrackedScript] = pydantic.Field(
        default_factory=list
    )
    groups: list[tracking_data.ScriptGroup] = pydantic.Field(default_factory=list)
    all_scripts: list[tracking_data.TrackedScript] = pydantic.Field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def group_similar_scripts(scripts: list[tracking_data.TrackedScript]) -> GroupedScriptsResult:
    """Group similar scripts together to reduce noise."""
    domain_groups: dict[str, dict[str, list[tracking_data.TrackedScript]]] = {}
    individual_scripts: list[tracking_data.TrackedScript] = []
    all_scripts: list[tracking_data.TrackedScript] = []

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

    groups: list[tracking_data.ScriptGroup] = []
    for key, pattern_map in domain_groups.items():
        domain, pattern_id = key.split(":", 1)
        pattern_info = next((p for p in GROUPABLE_PATTERNS if p.id == pattern_id), None)

        for _, scripts_in_group in pattern_map.items():
            if len(scripts_in_group) >= MIN_GROUP_SIZE and pattern_info:
                group_id = f"{domain}-{pattern_id}"
                groups.append(tracking_data.ScriptGroup(
                    id=group_id,
                    name=pattern_info.name,
                    description=f"{len(scripts_in_group)} {pattern_info.description.lower()}",
                    count=len(scripts_in_group),
                    example_urls=[s.url for s in scripts_in_group[:3]],
                    domain=domain,
                ))
                for s in scripts_in_group:
                    all_scripts.append(tracking_data.TrackedScript(
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_groupable_pattern(url: str) -> GroupPattern | None:
    for gp in GROUPABLE_PATTERNS:
        if gp.pattern.search(url):
            return gp
    return None
