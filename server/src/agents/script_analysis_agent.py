"""Script analysis agent for LLM-based script identification.

Analyses individual JavaScript file URLs and content to
determine their purpose using structured JSON output.
"""

from __future__ import annotations

import pydantic

from src.agents import base, config
from src.agents.prompts import script_analysis
from src.utils import errors, json_parsing, logger

log = logger.create_logger("ScriptAnalysisAgent")


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

    async def analyze_one(
        self,
        url: str,
        content: str | None = None,
    ) -> str | None:
        """Analyse a single script.

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
        log.debug("Analysing script", {"url": url})

        try:
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
