"""Cookie information agent for LLM-based cookie identification.

Analyses individual browser cookies to determine their purpose,
the service that sets them, and their privacy implications.
Falls back to LLM only when the cookie is not found in the
known consent-cookie or tracker-pattern databases.
"""

from __future__ import annotations

from src.agents import base, config
from src.agents.prompts import cookie_info
from src.models import item_info

# ── Structured output model ─────────────────────────────────────


class CookieInfoResult(item_info.ItemInfoResult):
    """LLM response describing a single cookie."""


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
        truncated_value = value[:200] if value else "[empty]"
        user_message = f"Cookie name: {name}\nDomain: {domain}\nValue: {truncated_value}"

        return await self._explain_item(
            user_message,
            CookieInfoResult,
            log_label="cookie info",
            log_context={"name": name, "domain": domain},
        )
