"""Tests for src.agents.config — LLM configuration validation."""

from __future__ import annotations

from unittest import mock

import pytest

from src.agents.config import (
    AGENT_CONSENT_DETECTION,
    AGENT_CONSENT_EXTRACTION,
    AGENT_SCRIPT_ANALYSIS,
    AGENT_STRUCTURED_REPORT,
    AGENT_SUMMARY_FINDINGS,
    AGENT_TRACKING_ANALYSIS,
    AzureOpenAIConfig,
    OpenAIConfig,
    get_agent_deployment,
    validate_llm_config,
)


class TestAgentNames:
    def test_all_defined(self) -> None:
        names = [
            AGENT_TRACKING_ANALYSIS,
            AGENT_SUMMARY_FINDINGS,
            AGENT_CONSENT_DETECTION,
            AGENT_CONSENT_EXTRACTION,
            AGENT_SCRIPT_ANALYSIS,
            AGENT_STRUCTURED_REPORT,
        ]
        assert all(isinstance(n, str) and n for n in names)


class TestAzureOpenAIConfig:
    def test_defaults_are_empty(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            cfg = AzureOpenAIConfig()
        assert cfg.validate_config() is False

    def test_valid_when_all_set(self) -> None:
        env = {
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
            "AZURE_OPENAI_API_KEY": "key123",
            "AZURE_OPENAI_DEPLOYMENT": "gpt-4o",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = AzureOpenAIConfig()
        assert cfg.validate_config() is True

    def test_invalid_without_deployment(self) -> None:
        env = {
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
            "AZURE_OPENAI_API_KEY": "key123",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = AzureOpenAIConfig()
        assert cfg.validate_config() is False


class TestOpenAIConfig:
    def test_defaults_are_empty(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            cfg = OpenAIConfig()
        assert cfg.validate_config() is False

    def test_valid_with_api_key(self) -> None:
        env = {"OPENAI_API_KEY": "sk-test-key"}
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = OpenAIConfig()
        assert cfg.validate_config() is True


class TestValidateLlmConfig:
    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        """Clear the lru_cache between tests so env changes take effect."""
        validate_llm_config.cache_clear()

    def test_returns_error_when_nothing_set(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            result = validate_llm_config()
        assert result is not None
        assert "not configured" in result.lower()

    def test_returns_none_when_azure_configured(self) -> None:
        env = {
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
            "AZURE_OPENAI_API_KEY": "key123",
            "AZURE_OPENAI_DEPLOYMENT": "gpt-4o",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            result = validate_llm_config()
        assert result is None

    def test_returns_none_when_openai_configured(self) -> None:
        env = {"OPENAI_API_KEY": "sk-test"}
        with mock.patch.dict("os.environ", env, clear=True):
            result = validate_llm_config()
        assert result is None


class TestGetAgentDeployment:
    """Tests for per-agent deployment overrides."""

    def test_returns_none_for_unknown_agent(self) -> None:
        assert get_agent_deployment("UnknownAgent") is None

    def test_returns_none_when_env_var_not_set(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            assert get_agent_deployment(AGENT_SCRIPT_ANALYSIS) is None

    def test_returns_none_when_env_var_empty(self) -> None:
        with mock.patch.dict("os.environ", {"AZURE_OPENAI_SCRIPT_DEPLOYMENT": ""}):
            assert get_agent_deployment(AGENT_SCRIPT_ANALYSIS) is None

    def test_returns_none_when_env_var_whitespace(self) -> None:
        with mock.patch.dict("os.environ", {"AZURE_OPENAI_SCRIPT_DEPLOYMENT": "  "}):
            assert get_agent_deployment(AGENT_SCRIPT_ANALYSIS) is None

    def test_returns_deployment_when_set(self) -> None:
        with mock.patch.dict("os.environ", {"AZURE_OPENAI_SCRIPT_DEPLOYMENT": "gpt-5.1-codex-mini"}):
            assert get_agent_deployment(AGENT_SCRIPT_ANALYSIS) == "gpt-5.1-codex-mini"

    def test_strips_whitespace(self) -> None:
        with mock.patch.dict("os.environ", {"AZURE_OPENAI_SCRIPT_DEPLOYMENT": "  codex-mini  "}):
            assert get_agent_deployment(AGENT_SCRIPT_ANALYSIS) == "codex-mini"

    def test_no_override_for_other_agents(self) -> None:
        """Non-script agents have no override mapping."""
        with mock.patch.dict("os.environ", {"AZURE_OPENAI_SCRIPT_DEPLOYMENT": "codex-mini"}):
            assert get_agent_deployment(AGENT_TRACKING_ANALYSIS) is None
            assert get_agent_deployment(AGENT_STRUCTURED_REPORT) is None
