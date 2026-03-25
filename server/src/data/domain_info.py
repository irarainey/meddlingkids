"""Cross-category domain description and storage key hints.

``get_domain_description`` combines tracker, partner, and
Disconnect databases to produce a single description for any
domain.  ``get_storage_key_hint`` matches storage keys against
the tracking-storage pattern database.
"""

from __future__ import annotations

import functools

from src.data import geo_loader, partner_loader, tracker_loader
from src.utils import url as url_mod

# Categories that are too generic to be useful as the sole label.
_GENERIC_CATEGORIES = {"Email", "Content"}


@functools.cache
def _get_company_name_index() -> dict[str, str]:
    """Pre-build a lowercased company name -> URL lookup from partner databases."""
    index: dict[str, str] = {}
    for cfg in partner_loader.PARTNER_CATEGORIES:
        db = partner_loader.get_partner_database(cfg.file)
        for name, entry in db.items():
            if entry.url:
                key = name.strip().lower()
                if key not in index:
                    index[key] = entry.url
    return index


def _find_company_url(company: str) -> str | None:
    """Look up a company URL from partner databases by company name."""
    return _get_company_name_index().get(company.strip().lower())


@functools.cache
def _get_partner_domain_index() -> dict[str, dict[str, str | None]]:
    """Pre-build a domain -> description lookup from partner databases.

    Iterates every partner database once and indexes entries by
    the domain extracted from their URL.  ``get_domain_description``
    uses this index for O(1) partner lookups instead of a linear
    scan on every call.
    """
    index: dict[str, dict[str, str | None]] = {}

    for cfg in partner_loader.PARTNER_CATEGORIES:
        db = partner_loader.get_partner_database(cfg.file)
        cat_label = cfg.category.replace("-", " ").title()
        for name, entry in db.items():
            entry_domain = (entry.url or "").replace("https://", "").replace("http://", "").rstrip("/").split("/")[0].removeprefix("www.")
            if not entry_domain or entry_domain in index:
                continue
            url = entry.url or f"https://{entry_domain}"
            index[entry_domain] = {
                "company": name.title(),
                "description": f"{cat_label} service",
                "url": url,
            }
    return index


def get_domain_description(domain: str) -> dict[str, str | None]:
    """Build a short description for a domain from known databases.

    Checks Disconnect services (category + company), the partner
    domain index, and the tracker-domains list.  Returns a dict
    with ``company``, ``description``, and ``url`` keys (any may
    be ``None``).
    """
    # Normalise: cookie domains often have a leading dot (e.g. ".google.com").
    domain = domain.lstrip(".")

    company: str | None = None
    description: str | None = None

    # 1. Disconnect services — richest metadata (category + company).
    services = tracker_loader.get_disconnect_services()
    info = services.get(domain)
    if not info:
        base = url_mod.get_base_domain(domain)
        info = services.get(base)
    if info:
        company = info.get("company")
        raw_cats: str | list[str] = info.get("category", "Tracking")
        cats = raw_cats if isinstance(raw_cats, list) else [raw_cats]
        labels = [tracker_loader._humanise_disconnect_category(c) for c in cats if c not in _GENERIC_CATEGORIES]
        if not labels:
            labels = [tracker_loader._humanise_disconnect_category(c) for c in cats]
        cat_label = ", ".join(dict.fromkeys(labels))  # deduplicate, preserve order
        description = f"{cat_label} service" + (f" by {company}" if company else "")
        # Try to find the company URL from partner databases rather
        # than fabricating one from the tracking domain.
        url = _find_company_url(company) if company else None
        country = geo_loader.lookup_country_for_domain(domain)
        return {"company": company, "description": description, "url": url, "country": country}

    # 2. Partner databases — O(1) lookup via pre-built domain index.
    partner_index = _get_partner_domain_index()
    hit = partner_index.get(domain) or partner_index.get(url_mod.get_base_domain(domain))
    if hit:
        result = dict(hit)
        result["country"] = geo_loader.lookup_country_for_domain(domain)
        return result

    # 3. Tracker-domains — minimal info (block/cookieblock).
    if tracker_loader.is_known_tracker_domain(domain):
        country = geo_loader.lookup_country_for_domain(domain)
        return {"company": None, "description": "Known tracking domain", "url": None, "country": country}

    country = geo_loader.lookup_country_for_domain(domain)
    return {"company": None, "description": None, "url": None, "country": country}


def get_storage_key_hint(key: str) -> dict[str, str | None]:
    """Return a brief hint for a storage key from the tracking-storage database.

    Matches *key* against the compiled tracking-storage patterns.
    Returns a dict with ``setBy`` and ``description`` (either may
    be ``None`` when no match is found).
    """
    patterns = tracker_loader.get_tracking_storage_patterns()
    for pattern, desc, set_by, _purpose in patterns:
        if pattern.search(key):
            return {"setBy": set_by, "description": desc}
    return {"setBy": None, "description": None}
