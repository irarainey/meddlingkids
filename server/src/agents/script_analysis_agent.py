"""Script analysis agent for LLM-based script identification.

Analyses individual JavaScript file URLs and content to
determine their purpose using structured JSON output.
Supports both chat-completion and legacy-completion
deployments (e.g. Codex models).
"""

from __future__ import annotations

import json

import pydantic

from src.agents import base, config
from src.agents.prompts import script_analysis
from src.utils import errors, json_parsing, logger

log = logger.create_logger("ScriptAnalysisAgent")


def _is_codex_deployment(deployment: str | None) -> bool:
    """Return ``True`` when *deployment* names a Codex model.

    Codex models use the legacy Completions API, not the
    Chat Completions API.
    """
    return bool(deployment and "codex" in deployment.lower())


# ── Structured output models ───────────────────────────────────


class _ScriptResult(pydantic.BaseModel):
    """LLM response for a single script analysis."""

    description: str


MAX_SCRIPT_CONTENT_LENGTH = 2000


# ── Agent class ─────────────────────────────────────────────────


class ScriptAnalysisAgent(base.BaseAgent):
    """Text agent that analyses a single script.

    Receives a script URL with optional content snippet and
    returns a short description of its purpose.
    """

    agent_name = config.AGENT_SCRIPT_ANALYSIS
    instructions = script_analysis.INSTRUCTIONS
    max_tokens = 200
    max_retries = 5
    response_model = _ScriptResult

    @property
    def _uses_codex(self) -> bool:
        """Whether the current deployment is a Codex model."""
        return _is_codex_deployment(self._deployment) and not self._using_fallback

    async def analyze_one(
        self,
        url: str,
        content: str | None = None,
    ) -> str | None:
        """Analyse a single script.

        Routes to the legacy Completions API when the
        configured deployment is a Codex model, otherwise
        uses the standard Chat Completions path.

        If the configured deployment returns a non-retryable
        error (e.g. ``OperationNotSupported``), the agent
        switches to the fallback (default) deployment and
        retries the request once.

        Args:
            url: Script URL.
            content: Optional script content snippet.

        Returns:
            Short description string, or ``None`` on failure.
        """
        snippet = (content or "[Content not available]")[:MAX_SCRIPT_CONTENT_LENGTH]
        user_message = f"Script: {url}\n{snippet}"
        log.debug("Analysing script", {"url": url, "codex": self._uses_codex})

        try:
            if self._uses_codex:
                return await self._try_complete_codex(user_message, url)
            return await self._try_complete(user_message, url)
        except Exception as error:
            # If the error looks like a model-level rejection
            # and we have a fallback, switch and retry once.
            if self.has_fallback and _is_model_error(error):
                log.warn(
                    "Deployment unsupported, falling back",
                    {
                        "url": url,
                        "error": errors.get_error_message(error),
                    },
                )
                self.activate_fallback()
                try:
                    return await self._try_complete(
                        user_message,
                        url,
                    )
                except Exception as retry_error:
                    log.error(
                        "Script analysis failed after fallback",
                        {
                            "url": url,
                            "error": errors.get_error_message(
                                retry_error,
                            ),
                        },
                    )
                    return None

            log.error(
                "Script analysis failed",
                {
                    "url": url,
                    "error": errors.get_error_message(error),
                },
            )
            return None

    async def _try_complete(
        self,
        user_message: str,
        url: str,
    ) -> str | None:
        """Attempt a single LLM completion for a script.

        Args:
            user_message: Formatted prompt with URL and content.
            url: Script URL (for logging context).

        Returns:
            Short description string, or ``None`` on parse
            failure.
        """
        response = await self._complete(user_message)

        parsed = self._parse_response(response, _ScriptResult)
        if parsed and parsed.description:
            return parsed.description

        # Fallback: try to extract from raw text.
        raw = json_parsing.load_json_from_text(response.text)
        if isinstance(raw, dict):
            return raw.get("description")

        return None


    async def _try_complete_codex(
        self,
        user_message: str,
        url: str,
    ) -> str | None:
        """Attempt a Codex completion via the legacy Completions API.

        Codex models do not support the Chat Completions
        endpoint.  This method accesses the underlying
        ``AsyncAzureOpenAI`` client and calls
        ``client.completions.create()`` directly.

        Args:
            user_message: Formatted prompt with URL and content.
            url: Script URL (for logging context).

        Returns:
            Short description string, or ``None`` on parse
            failure.
        """
        if self._chat_client is None:
            return None

        # Access the underlying openai SDK client stored by
        # the agent-framework's AzureOpenAIChatClient.
        sdk_client = getattr(self._chat_client, "client", None)
        if sdk_client is None:
            # Client may need async initialisation first.
            ensure = getattr(self._chat_client, "_ensure_client", None)
            if ensure:
                sdk_client = await ensure()
            if sdk_client is None:
                log.error("Cannot access underlying SDK client for Codex completion")
                return None

        prompt = (
            f"{self.instructions}\n\n"
            f"{user_message}\n\n"
            "Respond with ONLY a JSON object: {{\"description\": \"...\"}}"
        )
        log.debug("Codex completion", {"url": url, "deployment": self._deployment})

        response = await sdk_client.completions.create(
            model=self._deployment or "",
            prompt=prompt,
            max_tokens=self.max_tokens,
            temperature=0,
            stop=["\n\n"],
        )

        text = (response.choices[0].text or "").strip() if response.choices else ""
        if not text:
            log.warn("Codex returned empty response", {"url": url})
            return None

        raw = json_parsing.load_json_from_text(text)
        if isinstance(raw, dict) and raw.get("description"):
            return raw["description"]

        # If the response isn't valid JSON, use the raw text
        # as the description (Codex may return plain text).
        if text and not text.startswith("{"):
            return text[:100]

        return None


def _is_model_error(error: BaseException) -> bool:
    """Check if the error indicates the model is unsupported.

    Detects Azure ``OperationNotSupported`` (HTTP 400) and
    similar model-level rejections that will never succeed
    on retry with the same deployment.

    Args:
        error: The exception to inspect.

    Returns:
        ``True`` when the error is a permanent model issue.
    """
    err_str = str(error).lower()
    return "operationnotsupported" in err_str or "does not work with the specified model" in err_str
