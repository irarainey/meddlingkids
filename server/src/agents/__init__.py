"""Agents package — domain-specific agents built on MAF.

Each agent owns its system prompt, response schema, and
parsing logic.  Shared infrastructure (chat client, retry,
timing) lives in ``base.py`` and ``middleware.py``.

Singleton access is provided via ``get_<agent>()`` helpers
so each agent is created once and reused.
"""

from __future__ import annotations

from src.agents.config import validate_llm_config
from src.agents.consent_detection_agent import (
    ConsentDetectionAgent,
)
from src.agents.consent_extraction_agent import (
    ConsentExtractionAgent,
)
from src.agents.script_analysis_agent import (
    ScriptAnalysisAgent,
)
from src.agents.summary_findings_agent import (
    SummaryFindingsAgent,
)
from src.agents.tracking_analysis_agent import (
    TrackingAnalysisAgent,
)
from src.utils import logger

log = logger.create_logger("Agents")


# ── Singletons ─────────────────────────────────────────────────

_consent_detection: ConsentDetectionAgent | None = None
_consent_extraction: ConsentExtractionAgent | None = None
_tracking_analysis: TrackingAnalysisAgent | None = None
_summary_findings: SummaryFindingsAgent | None = None
_script_analysis: ScriptAnalysisAgent | None = None


def _init_agent(agent_cls: type) -> object:
    """Instantiate and initialise an agent, logging on failure.

    Args:
        agent_cls: The agent class to create.

    Returns:
        Initialised agent instance.
    """
    agent = agent_cls()
    if not agent.initialise():
        log.warn(
            f"{agent_cls.__name__} created but LLM not"
            " configured — calls will fail until config"
            " is set."
        )
    return agent


def get_consent_detection_agent() -> ConsentDetectionAgent:
    """Get the singleton ``ConsentDetectionAgent``."""
    global _consent_detection
    if _consent_detection is None:
        _consent_detection = _init_agent(
            ConsentDetectionAgent
        )
    return _consent_detection


def get_consent_extraction_agent() -> (
    ConsentExtractionAgent
):
    """Get the singleton ``ConsentExtractionAgent``."""
    global _consent_extraction
    if _consent_extraction is None:
        _consent_extraction = _init_agent(
            ConsentExtractionAgent
        )
    return _consent_extraction


def get_tracking_analysis_agent() -> TrackingAnalysisAgent:
    """Get the singleton ``TrackingAnalysisAgent``."""
    global _tracking_analysis
    if _tracking_analysis is None:
        _tracking_analysis = _init_agent(
            TrackingAnalysisAgent
        )
    return _tracking_analysis


def get_summary_findings_agent() -> SummaryFindingsAgent:
    """Get the singleton ``SummaryFindingsAgent``."""
    global _summary_findings
    if _summary_findings is None:
        _summary_findings = _init_agent(
            SummaryFindingsAgent
        )
    return _summary_findings


def get_script_analysis_agent() -> ScriptAnalysisAgent:
    """Get the singleton ``ScriptAnalysisAgent``."""
    global _script_analysis
    if _script_analysis is None:
        _script_analysis = _init_agent(
            ScriptAnalysisAgent
        )
    return _script_analysis


__all__ = [
    "ConsentDetectionAgent",
    "ConsentExtractionAgent",
    "ScriptAnalysisAgent",
    "SummaryFindingsAgent",
    "TrackingAnalysisAgent",
    "get_consent_detection_agent",
    "get_consent_extraction_agent",
    "get_script_analysis_agent",
    "get_summary_findings_agent",
    "get_tracking_analysis_agent",
    "validate_llm_config",
]
