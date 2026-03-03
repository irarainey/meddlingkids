"""Cookie information lookup service.

Provides cookie explanations by checking known databases first
(consent cookies, tracking patterns) and falling back to LLM
for unrecognised cookies.
"""

from __future__ import annotations

from src.agents import cookie_info_agent
from src.analysis import tracker_patterns
from src.data import loader
from src.models import item_info
from src.utils import logger

log = logger.create_logger("CookieLookup")


def _attach_vendor_metadata(result: cookie_info_agent.CookieInfoResult) -> cookie_info_agent.CookieInfoResult:
    """Enrich a cookie result with vendor cross-reference data."""
    return item_info.attach_vendor_metadata(result, loader.get_tracking_cookie_vendor_index())


def _check_known_consent_cookie(name: str) -> cookie_info_agent.CookieInfoResult | None:
    """Check if a cookie matches the consent-cookies database.

    Returns a pre-built result if found, avoiding an LLM call.
    """
    data = loader.get_consent_cookies()

    # Check TCF cookies by exact name
    tcf = data.get("tcf_cookies", {})
    if name in tcf:
        entry = tcf[name]
        return cookie_info_agent.CookieInfoResult(
            description=entry.get("description", "TCF consent cookie"),
            setBy=entry.get("set_by", entry.get("framework", "CMP")),
            purpose="consent",
            riskLevel="none",
            privacyNote="This is a consent management cookie — it stores your privacy preferences, not tracking data.",
        )

    # Check CMP cookies by exact name
    cmp = data.get("cmp_cookies", {})
    if name in cmp:
        entry = cmp[name]
        return cookie_info_agent.CookieInfoResult(
            description=entry.get("description", "Consent management cookie"),
            setBy=entry.get("set_by", "CMP"),
            purpose="consent",
            riskLevel="none",
            privacyNote="This is a consent management cookie — it stores your privacy preferences, not tracking data.",
        )

    return None


def _check_consent_pattern(name: str) -> bool:
    """Check if a cookie name matches a known consent-state pattern."""
    return any(p.search(name) for p in tracker_patterns.CONSENT_STATE_COOKIE_PATTERNS)


def _check_tracking_pattern(name: str) -> cookie_info_agent.CookieInfoResult | None:
    """Check if a cookie name matches known tracking cookie patterns.

    Returns a pre-built result if it matches a well-known tracker.
    """
    risk_map = loader.get_tracking_cookie_risk_map()
    privacy_map = loader.get_tracking_cookie_privacy_map()

    for pattern, description, set_by, purpose in loader.get_tracking_cookie_patterns():
        if pattern.search(name):
            return cookie_info_agent.CookieInfoResult(
                description=description,
                setBy=set_by,
                purpose=purpose,
                riskLevel=risk_map.get(purpose, "medium"),
                privacyNote=privacy_map.get(purpose, ""),
            )

    # Check generic tracking patterns
    if any(p.search(name) for p in tracker_patterns.TRACKING_COOKIE_PATTERNS):
        return cookie_info_agent.CookieInfoResult(
            description="Known tracking cookie — used for analytics or advertising purposes.",
            setBy="Third-party tracker",
            purpose="advertising",
            riskLevel="high",
            privacyNote="This cookie is associated with known tracking infrastructure.",
        )

    # Check fingerprint patterns
    if any(p.search(name) for p in tracker_patterns.FINGERPRINT_COOKIE_PATTERNS):
        return cookie_info_agent.CookieInfoResult(
            description="Fingerprinting-related cookie — used to create a unique device or browser identifier.",
            setBy="Fingerprinting service",
            purpose="fingerprinting",
            riskLevel="critical",
            privacyNote="Fingerprinting cookies enable persistent tracking that is difficult to opt out of.",
        )

    return None


async def get_cookie_info(
    name: str,
    domain: str,
    value: str,
    agent: cookie_info_agent.CookieInfoAgent,
) -> cookie_info_agent.CookieInfoResult:
    """Look up information about a cookie.

    Checks known databases first, then falls back to LLM.

    Args:
        name: Cookie name.
        domain: Cookie domain.
        value: Cookie value.
        agent: The LLM agent instance for fallback lookups.

    Returns:
        Structured cookie information.
    """
    # 1. Check consent-cookies database (exact match)
    result = _check_known_consent_cookie(name)
    if result:
        log.debug("Cookie found in consent database", {"name": name})
        return result

    # 2. Check consent-state patterns
    if _check_consent_pattern(name):
        log.debug("Cookie matches consent-state pattern", {"name": name})
        return cookie_info_agent.CookieInfoResult(
            description="Consent management cookie — stores privacy preference state.",
            setBy="Consent Management Platform",
            purpose="consent",
            riskLevel="none",
            privacyNote="This is a consent management cookie — it stores your privacy preferences, not tracking data.",
        )

    # 3. Check tracking patterns
    result = _check_tracking_pattern(name)
    if result:
        log.debug("Cookie matched tracking pattern", {"name": name})
        return _attach_vendor_metadata(result)

    # 4. Fall back to LLM
    log.info("Cookie not in databases, querying LLM", {"name": name, "domain": domain})
    llm_result = await agent.explain(name, domain, value)
    if llm_result:
        return llm_result

    # 5. Last resort — minimal generic info
    return cookie_info_agent.CookieInfoResult(
        description="Purpose could not be determined for this cookie.",
        setBy=domain,
        purpose="unknown",
        riskLevel="low",
        privacyNote="",
    )
