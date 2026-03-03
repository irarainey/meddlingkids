"""Media group profile loaders and LLM context builder."""

from __future__ import annotations

import functools
from typing import Any

from src.data import _base
from src.models import partners
from src.utils import url


@functools.cache
def get_media_groups() -> dict[str, partners.MediaGroupProfile]:
    """Get media group profiles (loaded once and cached).

    Returns a dictionary mapping lowercase group names to
    their MediaGroupProfile containing ownership, properties,
    domains, key vendors, and privacy characteristics.
    """
    raw: dict[str, dict[str, Any]] = _base._load_json("publishers/media-groups.json")
    result = {key: partners.MediaGroupProfile(**val) for key, val in raw.items()}
    _base.log.info("Media groups loaded", {"count": len(result)})
    return result


def find_media_group_by_domain(domain: str) -> tuple[str, partners.MediaGroupProfile] | None:
    """Look up a media group by one of its known domains.

    Strips a leading ``www.`` prefix and also tries the
    registrable base domain (e.g. ``example.co.uk`` from
    ``sub.example.co.uk``) so callers don't need to
    normalise beforehand.

    Args:
        domain: A domain name (e.g. 'thesun.co.uk') to search for.

    Returns:
        A tuple of (group_name, profile) if found, or None.
    """
    domain_lower = domain.lower().strip()
    # Build candidate set: original, without www., and base domain.
    candidates = {domain_lower}
    if domain_lower.startswith("www."):
        candidates.add(domain_lower[4:])
    candidates.add(url.get_base_domain(domain_lower))

    for name, profile in get_media_groups().items():
        if candidates & set(profile.domains):
            return (name, profile)
    return None


def build_media_group_context(analyzed_url: str) -> str:
    """Build media group context for LLM prompts.

    Extracts the domain from *analyzed_url*, looks up a
    matching media group profile, and returns a formatted
    reference section.  Returns an empty string when no
    match is found.

    Args:
        analyzed_url: The full URL being analysed.

    Returns:
        Formatted media group context section, or ``""``.
    """
    hostname = url.extract_domain(analyzed_url)
    base_domain = url.get_base_domain(hostname)
    result = find_media_group_by_domain(base_domain)
    if result is None:
        return ""

    name, profile = result
    lines: list[str] = [
        "",
        "## Publisher / Media Group Context (Prior Research)",
        "",
        f"This site belongs to **{profile.parent}** (group key: {name}).",
        f"- Privacy policy: {profile.privacy_policy}",
        f"- Consent platform: {profile.consent_platform}",
        f"- Properties ({len(profile.properties)}): {', '.join(profile.properties[:10])}",
        f"- Known domains: {', '.join(profile.domains[:10])}",
        "",
        "### Key Vendors",
    ]
    for vendor in profile.key_vendors:
        lines.append(f"- {vendor}")
    lines.append("")
    lines.append("### Privacy Characteristics")
    for char in profile.privacy_characteristics:
        lines.append(f"- {char}")
    lines.append("")
    return "\n".join(lines)
