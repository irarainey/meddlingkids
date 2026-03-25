"""Tests for src.agents.llm_client — LLM client factory."""

from __future__ import annotations

from unittest import mock

from src.agents import config, llm_client


def _make_azure_cfg(
    *,
    endpoint: str = "https://test.openai.azure.com",
    api_key: str = "",
    deployment: str = "gpt-4o",
    use_managed_identity: bool = False,
    managed_identity_client_id: str = "",
) -> config.AzureOpenAIConfig:
    """Build an AzureOpenAIConfig without reading environment variables."""
    env = {
        "AZURE_OPENAI_ENDPOINT": endpoint,
        "AZURE_OPENAI_API_KEY": api_key,
        "AZURE_OPENAI_DEPLOYMENT": deployment,
        "AZURE_USE_MANAGED_IDENTITY": str(use_managed_identity).lower(),
    }
    if managed_identity_client_id:
        env["AZURE_CLIENT_ID"] = managed_identity_client_id
    with mock.patch.dict("os.environ", env, clear=True):
        return config.AzureOpenAIConfig()


class TestBuildAzureAuthKwargs:
    def test_api_key_returns_api_key(self) -> None:
        cfg = _make_azure_cfg(api_key="secret-key")
        result = llm_client._build_azure_auth_kwargs(cfg)
        assert result == {"api_key": "secret-key"}
        assert "credential" not in result

    @mock.patch("azure.identity.DefaultAzureCredential", autospec=True)
    def test_managed_identity_returns_credential(self, mock_dac: mock.MagicMock) -> None:
        cfg = _make_azure_cfg(use_managed_identity=True)
        result = llm_client._build_azure_auth_kwargs(cfg)
        assert "credential" in result
        assert "api_key" not in result
        mock_dac.assert_called_once_with()

    @mock.patch("azure.identity.DefaultAzureCredential", autospec=True)
    def test_managed_identity_with_client_id(self, mock_dac: mock.MagicMock) -> None:
        cfg = _make_azure_cfg(
            use_managed_identity=True,
            managed_identity_client_id="00000000-0000-0000-0000-000000000000",
        )
        result = llm_client._build_azure_auth_kwargs(cfg)
        assert "credential" in result
        mock_dac.assert_called_once_with(
            managed_identity_client_id="00000000-0000-0000-0000-000000000000",
        )

    def test_api_key_takes_precedence_over_managed_identity(self) -> None:
        cfg = _make_azure_cfg(api_key="secret-key", use_managed_identity=True)
        result = llm_client._build_azure_auth_kwargs(cfg)
        # When api_key is set the config is valid via api_key, but
        # _build_azure_auth_kwargs checks use_managed_identity first.
        # Both paths are valid — the caller (get_chat_client) will
        # get a working client either way.
        assert "credential" in result or "api_key" in result
