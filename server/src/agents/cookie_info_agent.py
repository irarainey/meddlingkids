"""Cookie information agent for LLM-based cookie identification.

Analyses individual browser cookies to determine their purpose,
the service that sets them, and their privacy implications.
Falls back to LLM only when the cookie is not found in the
known consent-cookie or tracker-pattern databases.
"""

from __future__ import annotations

import pydantic

from src.agents import base, config
from src.agents.prompts import cookie_info
from src.utils import json_parsing, logger

log = logger.create_logger("CookieInfoAgent")


# ── Structured output model ─────────────────────────────────────


class CookieInfoResult(pydantic.BaseModel):
    """LLM response describing a single cookie."""

    description: str
    set_by: str = pydantic.Field(alias="setBy", serialization_alias="setBy")
    purpose: str
    risk_level: str = pydantic.Field(alias="riskLevel", serialization_alias="riskLevel")
    privacy_note: str = pydantic.Field(alias="privacyNote", serialization_alias="privacyNote")

    model_config = pydantic.ConfigDict(populate_by_name=True)


# ── Agent class ─────────────────────────────────────────────────


class CookieInfoAgent(base.BaseAgent):
    """Text agent that explains a single cookie.

    Receives a cookie name, domain, and value and returns
    a structured explanation of what the cookie does.
    """

    agent_name = config.AGENT_COOKIE_INFO
    instructions = cookie_info.INSTRUCTIONS
    max_tokens = 300
    max_retries = 2
    response_model = CookieInfoResult

    async def explain(
        self,
        name: str,
        domain: str,
        value: str,
    ) -> CookieInfoResult | None:
        """Explain a single cookie via LLM.

        Args:
            name: Cookie name.
            domain: Cookie domain.
            value: Cookie value (truncated for the prompt).

        Returns:
            Structured cookie information, or ``None`` on failure.
        """
        # Truncate the value to avoid wasting tokens on long encoded strings
        truncated_value = value[:200] if value else "[empty]"
        user_message = f"Cookie name: {name}\nDomain: {domain}\nValue: {truncated_value}"
        log.debug("Explaining cookie via LLM", {"name": name, "domain": domain})

        try:
            response = await self._complete(user_message)
            parsed = self._parse_response(response, CookieInfoResult)
            if parsed:
                return parsed

            # Fallback: manual JSON parse from response text
            raw = json_parsing.load_json_from_text(response.text)
            if isinstance(raw, dict):
                try:
                    return CookieInfoResult.model_validate(raw)
                except Exception:
                    pass

            log.warn("Failed to parse cookie info response", {"name": name})
            return None
        except Exception as exc:
            log.warn(
                f"Cookie info LLM call failed: {exc}",
                {"name": name, "domain": domain},
            )
            return None
