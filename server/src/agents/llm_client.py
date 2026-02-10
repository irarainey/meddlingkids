"""
Chat client factory for Microsoft Agent Framework.

Supports both Azure OpenAI and standard OpenAI backends.
Automatically detects which backend to use based on environment
variables, preferring Azure when fully configured.
"""

from __future__ import annotations

from agent_framework import ChatClientProtocol, azure, openai

from src.agents import config
from src.utils import logger

log = logger.create_logger("LLM-Client")


def get_chat_client(
    agent_name: str | None = None,
) -> ChatClientProtocol | None:
    """Create and return a chat client for the configured LLM backend.

    Prefers Azure OpenAI when its environment variables are set.
    Falls back to standard OpenAI otherwise.

    Middleware should be added when creating ``ChatAgent`` instances,
    not at the client level.

    Args:
        agent_name: Optional name of the agent for logging context.

    Returns:
        A ``ChatClientProtocol`` instance, or ``None`` if
        configuration is missing.
    """
    azure_cfg = config.AzureOpenAIConfig()
    if azure_cfg.validate():
        return _create_azure_client(azure_cfg, agent_name)

    openai_cfg = config.OpenAIConfig()
    if openai_cfg.validate():
        return _create_openai_client(openai_cfg, agent_name)

    log.warn(
        "LLM not configured. Set either Azure OpenAI or"
        " standard OpenAI environment variables."
    )
    return None


def _create_azure_client(
    cfg: config.AzureOpenAIConfig,
    agent_name: str | None,
) -> ChatClientProtocol:
    """Instantiate an Azure OpenAI chat client.

    Args:
        cfg: Validated Azure OpenAI configuration.
        agent_name: Optional agent name for logging.

    Returns:
        An ``AzureOpenAIChatClient`` instance.
    """
    log.info("Using Azure OpenAI", {"agent": agent_name or "default"})

    return azure.AzureOpenAIChatClient(
        api_key=cfg.api_key,
        api_version=cfg.api_version,
        endpoint=cfg.endpoint,
        deployment_name=cfg.deployment,
    )


def _create_openai_client(
    cfg: config.OpenAIConfig,
    agent_name: str | None,
) -> ChatClientProtocol:
    """Instantiate a standard OpenAI chat client.

    Args:
        cfg: Validated OpenAI configuration.
        agent_name: Optional agent name for logging.

    Returns:
        An ``OpenAIChatClient`` instance.
    """
    log.info("Using standard OpenAI", {"agent": agent_name or "default"})

    return openai.OpenAIChatClient(
        api_key=cfg.api_key,
        model_id=cfg.model or None,
        base_url=cfg.base_url,
    )
