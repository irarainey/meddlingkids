"""
OpenAI client configuration and initialisation.
Supports both Azure OpenAI and standard OpenAI APIs.
Manages a singleton client instance for AI-powered analysis.
"""

from __future__ import annotations

import os

from openai import AsyncAzureOpenAI, AsyncOpenAI

from src.utils.logger import create_logger

log = create_logger("OpenAI")

_openai_client: AsyncOpenAI | AsyncAzureOpenAI | None = None
_is_azure: bool = False


def get_openai_client() -> AsyncOpenAI | AsyncAzureOpenAI | None:
    """
    Get or initialise the OpenAI client.
    Automatically detects whether to use Azure or standard OpenAI
    based on which environment variables are configured.
    """
    global _openai_client, _is_azure

    if _openai_client is not None:
        return _openai_client

    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    azure_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    azure_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")

    if azure_endpoint and azure_api_key and azure_deployment:
        log.info("Using Azure OpenAI")
        _is_azure = True
        _openai_client = AsyncAzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_api_key,
            api_version=os.environ.get("OPENAI_API_VERSION", "2024-12-01-preview"),
            azure_deployment=azure_deployment,
        )
        return _openai_client

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        log.info("Using standard OpenAI")
        _is_azure = False
        _openai_client = AsyncOpenAI(
            api_key=openai_api_key,
            base_url=os.environ.get("OPENAI_BASE_URL"),
        )
        return _openai_client

    log.warn(
        "OpenAI not configured. Set either:\n"
        "  Azure: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT\n"
        "  OpenAI: OPENAI_API_KEY (and optionally OPENAI_MODEL, OPENAI_BASE_URL)"
    )
    return None


def get_deployment_name() -> str:
    """
    Get the model/deployment name to use for API calls.
    For Azure, returns the deployment name.
    For standard OpenAI, returns the model name.

    Ensures the client is initialised first so that
    _is_azure is set correctly before reading it.
    """
    get_openai_client()
    if _is_azure:
        return os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
    return os.environ.get("OPENAI_MODEL", "")


def validate_openai_config() -> str | None:
    """
    Check if OpenAI is properly configured.
    Returns an error message if not configured, or None if configured.
    """
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    azure_api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    azure_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    openai_api_key = os.environ.get("OPENAI_API_KEY")

    if azure_endpoint and azure_api_key and azure_deployment:
        return None

    if openai_api_key:
        return None

    return (
        "OpenAI is not configured. Please set one of the following:\n"
        "  Azure OpenAI: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT\n"
        "  Standard OpenAI: OPENAI_API_KEY (and optionally OPENAI_MODEL, OPENAI_BASE_URL)"
    )
