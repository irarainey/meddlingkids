"""
Chat client factory for Microsoft Agent Framework.

Supports both Azure OpenAI and standard OpenAI backends.
Automatically detects which backend to use based on environment
variables, preferring Azure when fully configured.
"""

from __future__ import annotations

from agent_framework import SupportsChatGetResponse, azure, openai

from src.agents import config
from src.utils import logger

log = logger.create_logger("LLM-Client")


def get_chat_client(
    agent_name: str | None = None,
    *,
    deployment_override: str | None = None,
) -> SupportsChatGetResponse | None:
    """Create and return a chat client for the configured LLM backend.

    Prefers Azure OpenAI when its environment variables are set.
    Falls back to standard OpenAI otherwise.

    Middleware should be added when creating ``Agent`` instances,
    not at the client level.

    Args:
        agent_name: Optional name of the agent for logging context.
        deployment_override: Optional Azure deployment name that
            replaces the default ``AZURE_OPENAI_DEPLOYMENT``.

    Returns:
        A ``SupportsChatGetResponse`` instance, or ``None`` if
        configuration is missing.
    """
    azure_cfg = config.AzureOpenAIConfig()
    if azure_cfg.validate_config():
        return _create_azure_client(azure_cfg, agent_name, deployment_override)

    openai_cfg = config.OpenAIConfig()
    if openai_cfg.validate_config():
        return _create_openai_client(openai_cfg, agent_name)

    log.warn("LLM not configured. Set either Azure OpenAI or standard OpenAI environment variables.")
    return None


def _create_azure_client(
    cfg: config.AzureOpenAIConfig,
    agent_name: str | None,
    deployment_override: str | None = None,
) -> SupportsChatGetResponse:
    """Instantiate an Azure OpenAI chat client.

    Args:
        cfg: Validated Azure OpenAI configuration.
        agent_name: Optional agent name for logging.
        deployment_override: Optional deployment name that
            replaces ``cfg.deployment``.

    Returns:
        An ``AzureOpenAIChatClient`` instance.
    """
    deployment = deployment_override or cfg.deployment
    log.info(
        "Using Azure OpenAI",
        {
            "agent": agent_name or "default",
            "deployment": deployment,
            "endpoint": cfg.endpoint,
            "apiVersion": cfg.api_version,
        },
    )

    return azure.AzureOpenAIChatClient(  # type: ignore[return-value]
        api_key=cfg.api_key.get_secret_value(),
        api_version=cfg.api_version,
        endpoint=cfg.endpoint,
        deployment_name=deployment,
    )


def _create_openai_client(
    cfg: config.OpenAIConfig,
    agent_name: str | None,
) -> SupportsChatGetResponse:
    """Instantiate a standard OpenAI chat client.

    Args:
        cfg: Validated OpenAI configuration.
        agent_name: Optional agent name for logging.

    Returns:
        An ``OpenAIChatClient`` instance.
    """
    log.info(
        "Using standard OpenAI",
        {
            "agent": agent_name or "default",
            "model": cfg.model or "(default)",
        },
    )

    return openai.OpenAIChatClient(  # type: ignore[return-value]
        api_key=cfg.api_key.get_secret_value(),
        model_id=cfg.model or None,
        base_url=cfg.base_url,
    )
