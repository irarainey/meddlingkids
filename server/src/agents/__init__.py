"""
Agents package for LLM-based analysis using Microsoft Agent Framework.

Provides a unified chat agent abstraction that supports both Azure OpenAI
and standard OpenAI backends, replacing direct OpenAI client usage.
"""

from src.agents.chat_agent import ChatAgentService
from src.agents.config import validate_llm_config

__all__ = [
    "ChatAgentService",
    "validate_llm_config",
]
