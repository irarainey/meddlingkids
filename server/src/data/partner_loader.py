"""Partner database loaders and category configuration."""

from __future__ import annotations

import functools
from typing import Any

from src.data import _base
from src.models import partners

# ── Partner loading ─────────────────────────────────────────


def _load_partner_database(filename: str) -> dict[str, partners.PartnerEntry]:
    """Load partner database from a JSON file."""
    raw: dict[str, dict[str, Any]] = _base._load_json(f"partners/{filename}")
    return {
        key: partners.PartnerEntry(
            concerns=val.get("concerns", []),
            aliases=val.get("aliases", []),
            url=val.get("url", ""),
            privacy_url=val.get("privacy_url", ""),
            gvl_ids=val.get("gvl_ids", []),
            atp_ids=val.get("atp_ids", []),
        )
        for key, val in raw.items()
    }


@functools.cache
def get_partner_database(filename: str) -> dict[str, partners.PartnerEntry]:
    """Get a partner database by filename (loaded once per filename and cached)."""
    result = _load_partner_database(filename)
    _base.log.info("Partner database loaded", {"file": filename, "entries": len(result)})
    return result


# ── Partner category configuration ──────────────────────────

PARTNER_CATEGORIES: list[partners.PartnerCategoryConfig] = [
    partners.PartnerCategoryConfig(
        file="data-brokers.json",
        risk_level="critical",
        category="data-broker",
        reason="Known data broker that aggregates and sells personal information",
        risk_score=10,
    ),
    partners.PartnerCategoryConfig(
        file="identity-trackers.json",
        risk_level="critical",
        category="identity-resolution",
        reason="Identity resolution service that links your identity across devices and sites",
        risk_score=9,
    ),
    partners.PartnerCategoryConfig(
        file="session-replay.json",
        risk_level="high",
        category="cross-site-tracking",
        reason="Session replay service that records your interactions on the site",
        risk_score=8,
    ),
    partners.PartnerCategoryConfig(
        file="ad-networks.json",
        risk_level="high",
        category="advertising",
        reason="Major advertising network that tracks across many websites",
        risk_score=7,
    ),
    partners.PartnerCategoryConfig(
        file="mobile-sdk-trackers.json",
        risk_level="high",
        category="cross-site-tracking",
        reason="Mobile SDK tracker embedded in apps for user tracking",
        risk_score=7,
    ),
    partners.PartnerCategoryConfig(
        file="analytics-trackers.json",
        risk_level="medium",
        category="analytics",
        reason="Analytics or marketing platform that collects behavioral data",
        risk_score=5,
    ),
    partners.PartnerCategoryConfig(
        file="social-trackers.json",
        risk_level="medium",
        category="social-media",
        reason="Social media tracker that monitors social interactions across sites",
        risk_score=5,
    ),
    partners.PartnerCategoryConfig(
        file="consent-providers.json",
        risk_level="medium",
        category="personalization",
        reason="Consent management platform that may share consent signals",
        risk_score=4,
    ),
]
