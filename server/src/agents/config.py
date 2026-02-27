"""
LLM configuration for agent-based analysis.

Centralises all environment variable names, default values,
and configuration validation for both Azure OpenAI and
standard OpenAI backends.

Uses ``pydantic_settings.BaseSettings`` for automatic environment
variable binding, type coercion, and validation.
"""

from __future__ import annotations

import os

import pydantic
import pydantic_settings

from src.utils import logger

log = logger.create_logger("Agent-Config")

# Used by validate_llm_config and get_agent_deployment to
# surface configuration details during startup diagnostics.

# ── Agent names ─────────────────────────────────────────────────────
AGENT_TRACKING_ANALYSIS = "TrackingAnalysisAgent"
AGENT_SUMMARY_FINDINGS = "SummaryFindingsAgent"
AGENT_CONSENT_DETECTION = "ConsentDetectionAgent"
AGENT_CONSENT_EXTRACTION = "ConsentExtractionAgent"
AGENT_SCRIPT_ANALYSIS = "ScriptAnalysisAgent"
AGENT_STRUCTURED_REPORT = "StructuredReportAgent"
AGENT_COOKIE_INFO = "CookieInfoAgent"
AGENT_STORAGE_INFO = "StorageInfoAgent"


# Per-agent deployment overrides.
# Maps agent names to environment variable names that hold
# an alternative Azure deployment.  When the variable is set
# and non-empty, the agent uses that deployment instead of
# the default ``AZURE_OPENAI_DEPLOYMENT``.
_AGENT_DEPLOYMENT_OVERRIDES: dict[str, str] = {
    AGENT_SCRIPT_ANALYSIS: "AZURE_OPENAI_SCRIPT_DEPLOYMENT",
}


def get_agent_deployment(agent_name: str) -> str | None:
    """Return the deployment override for *agent_name*, if configured.

    Reads the environment variable mapped in
    ``_AGENT_DEPLOYMENT_OVERRIDES``.  Returns ``None`` when
    no override is configured so the caller falls back to the
    default deployment.
    """
    env_var = _AGENT_DEPLOYMENT_OVERRIDES.get(agent_name)
    if not env_var:
        return None

    value = os.environ.get(env_var, "").strip()
    if value:
        log.info(
            "Agent deployment override active",
            {"agent": agent_name, "deployment": value},
        )
    return value or None


class AzureOpenAIConfig(pydantic_settings.BaseSettings):
    """Configuration for Azure OpenAI chat client.

    Loads configuration from environment variables and validates
    that all required settings are present.

    Attributes:
        endpoint: Azure OpenAI service endpoint URL.
        api_key: API key for authentication.
        api_version: API version to use.
        deployment: Model deployment name.
    """

    endpoint: str = pydantic.Field(default="", validation_alias="AZURE_OPENAI_ENDPOINT")
    api_key: pydantic.SecretStr = pydantic.Field(
        default_factory=lambda: pydantic.SecretStr(""),
        validation_alias="AZURE_OPENAI_API_KEY",
    )
    api_version: str = pydantic.Field(
        default="2024-12-01-preview",
        validation_alias="OPENAI_API_VERSION",
    )
    deployment: str = pydantic.Field(default="", validation_alias="AZURE_OPENAI_DEPLOYMENT")

    def validate_config(self) -> bool:
        """Check if all required configuration is present.

        Returns:
            True when endpoint, api_key, and deployment are set.
        """
        return bool(self.endpoint and self.api_key.get_secret_value() and self.deployment)


class OpenAIConfig(pydantic_settings.BaseSettings):
    """Configuration for standard OpenAI chat client.

    Loads configuration from environment variables.

    Attributes:
        api_key: OpenAI API key.
        model: Model name (e.g. ``gpt-4o``).
        base_url: Optional custom base URL.
    """

    api_key: pydantic.SecretStr = pydantic.Field(
        default_factory=lambda: pydantic.SecretStr(""),
        validation_alias="OPENAI_API_KEY",
    )
    model: str = pydantic.Field(default="", validation_alias="OPENAI_MODEL")
    base_url: str | None = pydantic.Field(default=None, validation_alias="OPENAI_BASE_URL")

    def validate_config(self) -> bool:
        """Check if the API key is present.

        Returns:
            True when the API key is set.
        """
        return bool(self.api_key.get_secret_value())


def validate_llm_config() -> str | None:
    """Check if an LLM backend is properly configured.

    Returns:
        An error message string when misconfigured, or ``None`` if valid.
    """
    azure_cfg = AzureOpenAIConfig()
    if azure_cfg.validate_config():
        log.info(
            "LLM backend configured",
            {"provider": "Azure OpenAI", "deployment": azure_cfg.deployment},
        )
        return None

    openai_cfg = OpenAIConfig()
    if openai_cfg.validate_config():
        log.info(
            "LLM backend configured",
            {"provider": "OpenAI", "model": openai_cfg.model or "default"},
        )
        return None

    log.warn("No LLM backend configured")
    return (
        "LLM is not configured. Please set one of the following:\n"
        "  Azure OpenAI: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY,"
        " AZURE_OPENAI_DEPLOYMENT\n"
        "  Standard OpenAI: OPENAI_API_KEY (and optionally"
        " OPENAI_MODEL, OPENAI_BASE_URL)"
    )
