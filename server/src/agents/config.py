"""
LLM configuration for agent-based analysis.

Centralises all environment variable names, default values,
and configuration validation for both Azure OpenAI and
standard OpenAI backends.
"""

from __future__ import annotations

import os

from src.utils import logger

log = logger.create_logger("Agent-Config")

# ── Environment variable names ──────────────────────────────────────
# Azure OpenAI
ENV_AZURE_ENDPOINT = "AZURE_OPENAI_ENDPOINT"
ENV_AZURE_API_KEY = "AZURE_OPENAI_API_KEY"
ENV_AZURE_DEPLOYMENT = "AZURE_OPENAI_DEPLOYMENT"
ENV_AZURE_API_VERSION = "OPENAI_API_VERSION"

# Standard OpenAI
ENV_OPENAI_API_KEY = "OPENAI_API_KEY"
ENV_OPENAI_MODEL = "OPENAI_MODEL"
ENV_OPENAI_BASE_URL = "OPENAI_BASE_URL"

# ── Defaults ────────────────────────────────────────────────────────
DEFAULT_API_VERSION = "2024-12-01-preview"

# ── Agent names ─────────────────────────────────────────────────────
AGENT_TRACKING_ANALYSIS = "TrackingAnalysisAgent"
AGENT_SUMMARY_FINDINGS = "SummaryFindingsAgent"
AGENT_CONSENT_DETECTION = "ConsentDetectionAgent"
AGENT_CONSENT_EXTRACTION = "ConsentExtractionAgent"
AGENT_SCRIPT_ANALYSIS = "ScriptAnalysisAgent"


class AzureOpenAIConfig:
    """Configuration for Azure OpenAI chat client.

    Loads configuration from environment variables and validates
    that all required settings are present.

    Attributes:
        endpoint: Azure OpenAI service endpoint URL.
        api_key: API key for authentication.
        api_version: API version to use.
        deployment: Model deployment name.
    """

    def __init__(self) -> None:
        """Initialise configuration from environment variables."""
        self.endpoint = os.getenv(ENV_AZURE_ENDPOINT, "")
        self.api_key = os.getenv(ENV_AZURE_API_KEY, "")
        self.api_version = os.getenv(
            ENV_AZURE_API_VERSION, DEFAULT_API_VERSION
        )
        self.deployment = os.getenv(ENV_AZURE_DEPLOYMENT, "")

    def validate(self) -> bool:
        """Check if all required configuration is present.

        Returns:
            True when endpoint, api_key, and deployment are set.
        """
        return bool(self.endpoint and self.api_key and self.deployment)


class OpenAIConfig:
    """Configuration for standard OpenAI chat client.

    Loads configuration from environment variables.

    Attributes:
        api_key: OpenAI API key.
        model: Model name (e.g. ``gpt-4o``).
        base_url: Optional custom base URL.
    """

    def __init__(self) -> None:
        """Initialise configuration from environment variables."""
        self.api_key = os.getenv(ENV_OPENAI_API_KEY, "")
        self.model = os.getenv(ENV_OPENAI_MODEL, "")
        self.base_url = os.getenv(ENV_OPENAI_BASE_URL)

    def validate(self) -> bool:
        """Check if the API key is present.

        Returns:
            True when the API key is set.
        """
        return bool(self.api_key)


def validate_llm_config() -> str | None:
    """Check if an LLM backend is properly configured.

    Returns:
        An error message string when misconfigured, or ``None`` if valid.
    """
    if AzureOpenAIConfig().validate():
        return None
    if OpenAIConfig().validate():
        return None

    return (
        "LLM is not configured. Please set one of the following:\n"
        "  Azure OpenAI: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY,"
        " AZURE_OPENAI_DEPLOYMENT\n"
        "  Standard OpenAI: OPENAI_API_KEY (and optionally"
        " OPENAI_MODEL, OPENAI_BASE_URL)"
    )
