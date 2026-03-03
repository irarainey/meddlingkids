"""
Chat client factory for Microsoft Agent Framework.

Supports both Azure OpenAI and standard OpenAI backends.
Automatically detects which backend to use based on environment
variables, preferring Azure when fully configured.
"""

from __future__ import annotations

import agent_framework
from agent_framework import azure, openai

from src.agents import config
from src.utils import logger

log = logger.create_logger("LLM-Client")

# Minimum Azure API version required by the Responses API.
_MIN_RESPONSES_API_VERSION = "2025-03-01-preview"


def get_chat_client(
    agent_name: str | None = None,
    *,
    deployment_override: str | None = None,
    use_responses_api: bool = False,
) -> agent_framework.SupportsChatGetResponse | None:
    """Create and return a chat client for the configured LLM backend.

    Prefers Azure OpenAI when its environment variables are set.
    Falls back to standard OpenAI otherwise.

    Middleware should be added when creating ``Agent`` instances,
    not at the client level.

    Args:
        agent_name: Optional name of the agent for logging context.
        deployment_override: Optional Azure deployment name that
            replaces the default ``AZURE_OPENAI_DEPLOYMENT``.
        use_responses_api: When ``True``, create an
            ``AzureOpenAIResponsesClient`` instead of the
            default ``AzureOpenAIChatClient``.  Required
            for deployments (e.g. codex models) that only
            support the Responses API.

    Returns:
        A ``SupportsChatGetResponse`` instance, or ``None`` if
        configuration is missing.
    """
    azure_cfg = config.AzureOpenAIConfig()
    if azure_cfg.validate_config():
        return _create_azure_client(
            azure_cfg,
            agent_name,
            deployment_override,
            use_responses_api,
        )

    openai_cfg = config.OpenAIConfig()
    if openai_cfg.validate_config():
        return _create_openai_client(openai_cfg, agent_name)

    log.warn("LLM not configured. Set either Azure OpenAI or standard OpenAI environment variables.")
    return None


def _create_azure_client(
    cfg: config.AzureOpenAIConfig,
    agent_name: str | None,
    deployment_override: str | None = None,
    use_responses_api: bool = False,
) -> agent_framework.SupportsChatGetResponse:
    """Instantiate an Azure OpenAI client.

    When *use_responses_api* is ``True``, an
    ``AzureOpenAIResponsesClient`` is created, which calls
    the Responses API instead of Chat Completions.  This is
    required for models (e.g. codex) that do not support the
    Chat Completions endpoint.

    Args:
        cfg: Validated Azure OpenAI configuration.
        agent_name: Optional agent name for logging.
        deployment_override: Optional deployment name that
            replaces ``cfg.deployment``.
        use_responses_api: When ``True``, use the Responses
            API client.

    Returns:
        An ``AzureOpenAIChatClient`` or
        ``AzureOpenAIResponsesClient`` instance.
    """
    deployment = deployment_override or cfg.deployment
    client_kind = "Responses" if use_responses_api else "ChatCompletion"

    # The Responses API requires api-version 2025-03-01-preview
    # or later.  When the configured version is older, override
    # it automatically so the client doesn't 400 immediately.
    api_version = cfg.api_version
    if use_responses_api and api_version < _MIN_RESPONSES_API_VERSION:
        log.info(
            "Upgrading api-version for Responses API",
            {"configured": api_version, "minimum": _MIN_RESPONSES_API_VERSION},
        )
        api_version = _MIN_RESPONSES_API_VERSION

    log.info(
        "Using Azure OpenAI",
        {
            "agent": agent_name or "default",
            "deployment": deployment,
            "endpoint": cfg.endpoint,
            "apiVersion": api_version,
            "clientKind": client_kind,
        },
    )

    if use_responses_api:
        return azure.AzureOpenAIResponsesClient(  # type: ignore[return-value]
            api_key=cfg.api_key.get_secret_value(),
            api_version=api_version,
            endpoint=cfg.endpoint,
            deployment_name=deployment,
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
) -> agent_framework.SupportsChatGetResponse:
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
