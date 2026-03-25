"""Tests for src.agents.config — LLM configuration validation."""

from __future__ import annotations

from unittest import mock

import pytest

from src.agents import config


class TestAgentNames:
    def test_all_defined(self) -> None:
        names = [
            config.AGENT_TRACKING_ANALYSIS,
            config.AGENT_SUMMARY_FINDINGS,
            config.AGENT_CONSENT_DETECTION,
            config.AGENT_CONSENT_EXTRACTION,
            config.AGENT_SCRIPT_ANALYSIS,
            config.AGENT_STRUCTURED_REPORT,
        ]
        assert all(isinstance(n, str) and n for n in names)


class TestAzureOpenAIConfig:
    def test_defaults_are_empty(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            cfg = config.AzureOpenAIConfig()
        assert cfg.validate_config() is False

    def test_valid_when_all_set(self) -> None:
        env = {
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
            "AZURE_OPENAI_API_KEY": "key123",
            "AZURE_OPENAI_DEPLOYMENT": "gpt-4o",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = config.AzureOpenAIConfig()
        assert cfg.validate_config() is True

    def test_invalid_without_deployment(self) -> None:
        env = {
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
            "AZURE_OPENAI_API_KEY": "key123",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = config.AzureOpenAIConfig()
        assert cfg.validate_config() is False

    def test_valid_with_managed_identity(self) -> None:
        env = {
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
            "AZURE_OPENAI_DEPLOYMENT": "gpt-4o",
            "AZURE_USE_MANAGED_IDENTITY": "true",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = config.AzureOpenAIConfig()
        assert cfg.validate_config() is True
        assert cfg.use_managed_identity is True

    def test_managed_identity_without_endpoint_is_invalid(self) -> None:
        env = {
            "AZURE_OPENAI_DEPLOYMENT": "gpt-4o",
            "AZURE_USE_MANAGED_IDENTITY": "true",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = config.AzureOpenAIConfig()
        assert cfg.validate_config() is False

    def test_managed_identity_with_client_id(self) -> None:
        env = {
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
            "AZURE_OPENAI_DEPLOYMENT": "gpt-4o",
            "AZURE_USE_MANAGED_IDENTITY": "true",
            "AZURE_CLIENT_ID": "00000000-0000-0000-0000-000000000000",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = config.AzureOpenAIConfig()
        assert cfg.validate_config() is True
        assert cfg.managed_identity_client_id == "00000000-0000-0000-0000-000000000000"

    def test_api_key_preferred_when_both_set(self) -> None:
        env = {
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
            "AZURE_OPENAI_API_KEY": "key123",
            "AZURE_OPENAI_DEPLOYMENT": "gpt-4o",
            "AZURE_USE_MANAGED_IDENTITY": "true",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = config.AzureOpenAIConfig()
        assert cfg.validate_config() is True
        assert cfg.api_key.get_secret_value() == "key123"


class TestOpenAIConfig:
    def test_defaults_are_empty(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            cfg = config.OpenAIConfig()
        assert cfg.validate_config() is False

    def test_valid_with_api_key(self) -> None:
        env = {"OPENAI_API_KEY": "sk-test-key"}
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = config.OpenAIConfig()
        assert cfg.validate_config() is True


class TestValidateLlmConfig:
    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        """Clear the lru_cache between tests so env changes take effect."""
        config.validate_llm_config.cache_clear()

    def test_returns_error_when_nothing_set(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            result = config.validate_llm_config()
        assert result is not None
        assert "not configured" in result.lower()

    def test_returns_none_when_azure_configured(self) -> None:
        env = {
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
            "AZURE_OPENAI_API_KEY": "key123",
            "AZURE_OPENAI_DEPLOYMENT": "gpt-4o",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            result = config.validate_llm_config()
        assert result is None

    def test_returns_none_when_azure_managed_identity_configured(self) -> None:
        env = {
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
            "AZURE_OPENAI_DEPLOYMENT": "gpt-4o",
            "AZURE_USE_MANAGED_IDENTITY": "true",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            result = config.validate_llm_config()
        assert result is None

    def test_returns_none_when_openai_configured(self) -> None:
        env = {"OPENAI_API_KEY": "sk-test"}
        with mock.patch.dict("os.environ", env, clear=True):
            result = config.validate_llm_config()
        assert result is None


class TestGetAgentDeployment:
    """Tests for per-agent deployment overrides."""

    def test_returns_none_for_unknown_agent(self) -> None:
        assert config.get_agent_deployment("UnknownAgent") is None

    def test_returns_none_when_env_var_not_set(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            assert config.get_agent_deployment(config.AGENT_SCRIPT_ANALYSIS) is None

    def test_returns_none_when_env_var_empty(self) -> None:
        with mock.patch.dict("os.environ", {"AZURE_OPENAI_SCRIPT_DEPLOYMENT": ""}):
            assert config.get_agent_deployment(config.AGENT_SCRIPT_ANALYSIS) is None

    def test_returns_none_when_env_var_whitespace(self) -> None:
        with mock.patch.dict("os.environ", {"AZURE_OPENAI_SCRIPT_DEPLOYMENT": "  "}):
            assert config.get_agent_deployment(config.AGENT_SCRIPT_ANALYSIS) is None

    def test_returns_deployment_when_set(self) -> None:
        with mock.patch.dict("os.environ", {"AZURE_OPENAI_SCRIPT_DEPLOYMENT": "gpt-5.1-codex-mini"}):
            assert config.get_agent_deployment(config.AGENT_SCRIPT_ANALYSIS) == "gpt-5.1-codex-mini"

    def test_strips_whitespace(self) -> None:
        with mock.patch.dict("os.environ", {"AZURE_OPENAI_SCRIPT_DEPLOYMENT": "  codex-mini  "}):
            assert config.get_agent_deployment(config.AGENT_SCRIPT_ANALYSIS) == "codex-mini"

    def test_no_override_for_other_agents(self) -> None:
        """Non-script agents have no override mapping."""
        with mock.patch.dict("os.environ", {"AZURE_OPENAI_SCRIPT_DEPLOYMENT": "codex-mini"}):
            assert config.get_agent_deployment(config.AGENT_TRACKING_ANALYSIS) is None
            assert config.get_agent_deployment(config.AGENT_STRUCTURED_REPORT) is None
