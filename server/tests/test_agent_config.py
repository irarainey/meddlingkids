"""Tests for src.agents.config — LLM configuration validation."""

from __future__ import annotations

from unittest import mock

from src.agents.config import (
    AGENT_CONSENT_DETECTION,
    AGENT_CONSENT_EXTRACTION,
    AGENT_SCRIPT_ANALYSIS,
    AGENT_STRUCTURED_REPORT,
    AGENT_SUMMARY_FINDINGS,
    AGENT_TRACKING_ANALYSIS,
    AzureOpenAIConfig,
    OpenAIConfig,
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
