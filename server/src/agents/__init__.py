"""Agents package — domain-specific agents built on MAF.

Each agent owns its system prompt, response schema, and
parsing logic.  Shared infrastructure (chat client, retry,
timing) lives in ``base.py`` and ``middleware.py``.

Singleton access is provided via ``get_<agent>()`` helpers
using ``functools.lru_cache`` so each agent is created once,
thread-safely, and reused.
"""

from __future__ import annotations

import functools

from src.agents import (
    base,
    consent_detection_agent,
    consent_extraction_agent,
    script_analysis_agent,
    structured_report_agent,
    summary_findings_agent,
    tracking_analysis_agent,
)
from src.utils import logger

log = logger.create_logger("Agents")


# ── Singletons ─────────────────────────────────────────────────


def _init_agent[T: base.BaseAgent](agent_cls: type[T]) -> T:
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


@functools.lru_cache(maxsize=1)
def get_consent_detection_agent() -> consent_detection_agent.ConsentDetectionAgent:
    """Get the singleton ``ConsentDetectionAgent``."""
    return _init_agent(consent_detection_agent.ConsentDetectionAgent)


@functools.lru_cache(maxsize=1)
def get_consent_extraction_agent() -> (
    consent_extraction_agent.ConsentExtractionAgent
):
    """Get the singleton ``ConsentExtractionAgent``."""
    return _init_agent(consent_extraction_agent.ConsentExtractionAgent)


@functools.lru_cache(maxsize=1)
def get_tracking_analysis_agent() -> tracking_analysis_agent.TrackingAnalysisAgent:
    """Get the singleton ``TrackingAnalysisAgent``."""
    return _init_agent(tracking_analysis_agent.TrackingAnalysisAgent)


@functools.lru_cache(maxsize=1)
def get_summary_findings_agent() -> summary_findings_agent.SummaryFindingsAgent:
    """Get the singleton ``SummaryFindingsAgent``."""
    return _init_agent(summary_findings_agent.SummaryFindingsAgent)


@functools.lru_cache(maxsize=1)
def get_script_analysis_agent() -> script_analysis_agent.ScriptAnalysisAgent:
    """Get the singleton ``ScriptAnalysisAgent``."""
    return _init_agent(script_analysis_agent.ScriptAnalysisAgent)


@functools.lru_cache(maxsize=1)
def get_structured_report_agent() -> structured_report_agent.StructuredReportAgent:
    """Get the singleton ``StructuredReportAgent``."""
    return _init_agent(structured_report_agent.StructuredReportAgent)


__all__ = [
    "get_consent_detection_agent",
    "get_consent_extraction_agent",
    "get_script_analysis_agent",
    "get_structured_report_agent",
    "get_summary_findings_agent",
    "get_tracking_analysis_agent",
]
