"""
Partner risk classification service.
Classifies consent partners by risk level based on their business practices.
Uses pattern matching for known entities.
"""

from __future__ import annotations

from src.data import loader
from src.models import consent
from src.models import partners as partners_mod


def _matches_partner(name_lower: str, key: str, aliases: list[str]) -> bool:
    """Check if a partner name matches a database entry."""
    return key in name_lower or any(a in name_lower for a in aliases)


def _classify_against_database(
    partner: consent.ConsentPartner,
    name_lower: str,
    database: dict[str, partners_mod.PartnerEntry],
    config: partners_mod.PartnerCategoryConfig,
) -> partners_mod.PartnerClassification | None:
    """Classify a partner against a specific database."""
    for key, data in database.items():
        if _matches_partner(name_lower, key, data.aliases):
            return partners_mod.PartnerClassification(
                name=partner.name,
                risk_level=config.risk_level,
                category=config.category,
                reason=config.reason,
                concerns=data.concerns,
                risk_score=config.risk_score,
            )
    return None


def _classify_by_purpose(partner: consent.ConsentPartner, purpose_lower: str) -> partners_mod.PartnerClassification | None:
    """Classify a partner based on its purpose text."""
    if any(w in purpose_lower for w in ("sell", "broker", "data marketplace")):
        return partners_mod.PartnerClassification(
            name=partner.name,
            risk_level="critical",
            category="data-broker",
            reason="Partner purpose indicates data selling or brokering",
            concerns=["Data selling disclosed in purpose"],
            risk_score=9,
        )

    if any(w in purpose_lower for w in ("cross-site", "cross-device", "identity")):
        return partners_mod.PartnerClassification(
            name=partner.name,
            risk_level="high",
            category="cross-site-tracking",
            reason="Partner purpose indicates cross-site or cross-device tracking",
            concerns=["Cross-site tracking disclosed"],
            risk_score=7,
        )

    if any(w in purpose_lower for w in ("advertising", "ads", "marketing")):
        return partners_mod.PartnerClassification(
            name=partner.name,
            risk_level="medium",
            category="advertising",
            reason="Advertising or marketing partner",
            concerns=["Behavioral targeting likely"],
            risk_score=5,
        )

    if any(w in purpose_lower for w in ("analytics", "measurement")):
        return partners_mod.PartnerClassification(
            name=partner.name,
            risk_level="medium",
            category="analytics",
            reason="Analytics or measurement partner",
            concerns=["Behavioral data collection"],
            risk_score=4,
        )

    if any(w in purpose_lower for w in ("fraud", "security", "bot")):
        return partners_mod.PartnerClassification(
            name=partner.name,
            risk_level="low",
            category="fraud-prevention",
            reason="Security or fraud prevention service",
            concerns=[],
            risk_score=2,
        )

    if any(w in purpose_lower for w in ("cdn", "content delivery", "hosting")):
        return partners_mod.PartnerClassification(
            name=partner.name,
            risk_level="low",
            category="content-delivery",
            reason="Content delivery or infrastructure partner",
            concerns=[],
            risk_score=1,
        )

    return None


def classify_partner_by_pattern_sync(
    partner: consent.ConsentPartner,
) -> partners_mod.PartnerClassification | None:
    """
    Classify a single partner based on known databases.
    Synchronous version for quick classification without LLM.
    """
    name_lower = partner.name.lower().strip()
    purpose_lower = (partner.purpose or "").lower()

    for config in loader.PARTNER_CATEGORIES:
        database = loader.get_partner_database(config.file)
        result = _classify_against_database(partner, name_lower, database, config)
        if result:
            return result

    return _classify_by_purpose(partner, purpose_lower)


def get_partner_risk_summary(
    partners: list[consent.ConsentPartner],
) -> partners_mod.PartnerRiskSummary:
    """
    Get a quick risk summary for partners without full classification.

    Uses only pattern matching for speed.
    """
    critical_count = 0
    high_count = 0
    total_risk_score = 0
    worst_partners: list[str] = []

    for partner in partners:
        result = classify_partner_by_pattern_sync(partner)
        if result:
            total_risk_score += result.risk_score
            if result.risk_level == "critical":
                critical_count += 1
                worst_partners.append(f"{partner.name} ({result.category})")
            elif result.risk_level == "high":
                high_count += 1
                if len(worst_partners) < 5:
                    worst_partners.append(f"{partner.name} ({result.category})")
        else:
            total_risk_score += 3  # Default for unknown

    return partners_mod.PartnerRiskSummary(
        critical_count=critical_count,
        high_count=high_count,
        total_risk_score=total_risk_score,
        worst_partners=worst_partners,
    )
