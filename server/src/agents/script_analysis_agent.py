"""Script analysis agent for LLM-based script identification.

Analyses individual JavaScript file URLs and content to
determine their purpose using structured JSON output.
"""

from __future__ import annotations

import pydantic

from src.agents import base, config
from src.utils import errors, json_parsing, logger

log = logger.create_logger("ScriptAnalysisAgent")


# ── Structured output models ───────────────────────────────────

class _ScriptResult(pydantic.BaseModel):
    """LLM response for a single script analysis."""

    description: str


# ── System prompt ───────────────────────────────────────────────

_INSTRUCTIONS = """\
You are a web security analyst. Analyse the given script URL \
and optional content snippet and briefly describe its purpose.

Provide a SHORT description (max 10 words) of what the \
script does. Focus on: tracking, analytics, advertising, \
functionality, UI framework, etc.

Return a JSON object with a "description" field."""

MAX_SCRIPT_CONTENT_LENGTH = 2000


# ── Agent class ─────────────────────────────────────────────────

class ScriptAnalysisAgent(base.BaseAgent):
    """Text agent that analyses a single script.

    Receives a script URL with optional content snippet and
    returns a short description of its purpose.
    """

    agent_name = config.AGENT_SCRIPT_ANALYSIS
    instructions = _INSTRUCTIONS
    max_tokens = 200
    max_retries = 5
    response_model = _ScriptResult

    async def analyze_one(
        self,
        url: str,
        content: str | None = None,
    ) -> str | None:
        """Analyse a single script.

        Args:
            url: Script URL.
            content: Optional script content snippet.

        Returns:
            Short description string, or ``None`` on failure.
        """
        snippet = (content or "[Content not available]")[
            :MAX_SCRIPT_CONTENT_LENGTH
        ]
        user_message = f"Script: {url}\n{snippet}"

        try:
            response = await self._complete(user_message)

            parsed = self._parse_response(
                response, _ScriptResult
            )
            if parsed and parsed.description:
                return parsed.description

            # Fallback: try to extract from raw text
            raw = json_parsing.load_json_from_text(
                response.text
            )
            if isinstance(raw, dict):
                return raw.get("description")

            return None
        except Exception as error:
            log.error(
                "Script analysis failed",
                {
                    "url": url,
                    "error": errors.get_error_message(error),
                },
            )
            return None
