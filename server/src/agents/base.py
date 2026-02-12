"""Base agent factory for domain-specific agents.

Provides shared infrastructure for creating agents with
consistent middleware, chat client, and structured output
configuration.  Each domain agent subclasses ``BaseAgent``
and defines its own instructions and response format.
"""

from __future__ import annotations

import base64
import copy
import io
import warnings
from typing import Any, TypeVar

import agent_framework
import pydantic
from PIL import Image

from src.agents import llm_client
from src.agents import middleware as middleware_mod
from src.utils import json_parsing, logger

log = logger.create_logger("BaseAgent")

T = TypeVar("T", bound=pydantic.BaseModel)


class BaseAgent:
    """Base class for all domain-specific agents.

    Manages a shared ``ChatClientProtocol`` and constructs
    purpose-specific ``ChatAgent`` contexts with timing and
    retry middleware baked in.

    Subclasses should set ``agent_name``, ``instructions``,
    ``max_tokens``, and optionally ``response_model`` to
    enable structured JSON output.

    Attributes:
        agent_name: Identifier for logging and middleware.
        instructions: System prompt sent to the LLM.
        max_tokens: Default maximum response tokens.
        max_retries: Retry attempts for transient failures.
        response_model: Optional Pydantic model for
            structured output via ``response_format``.
    """

    agent_name: str = "BaseAgent"
    instructions: str = ""
    max_tokens: int = 4096
    max_retries: int = 5
    response_model: type[pydantic.BaseModel] | None = None

    def __init__(self) -> None:
        """Initialise with a shared LLM chat client."""
        self._chat_client: (
            agent_framework.ChatClientProtocol | None
        ) = None
        self._timing = middleware_mod.TimingChatMiddleware(self.agent_name)
        self._retry = middleware_mod.RetryChatMiddleware(
            self.agent_name, max_retries=self.max_retries
        )

    def initialise(self) -> bool:
        """Create the underlying LLM chat client.

        Returns:
            ``True`` when the client was created.
        """
        self._chat_client = llm_client.get_chat_client(
            agent_name=self.agent_name
        )
        return self._chat_client is not None

    @property
    def is_configured(self) -> bool:
        """Whether the LLM client is ready."""
        return self._chat_client is not None

    # ── Agent construction ──────────────────────────────────────

    @staticmethod
    def _prepare_strict_schema(
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Make a Pydantic JSON schema compatible with Azure OpenAI strict mode.

        Azure OpenAI structured output requires every object
        in the schema to have ``additionalProperties: false``
        and all properties listed in ``required``.  Pydantic's
        ``model_json_schema()`` omits these, so we patch them
        in recursively.

        Args:
            schema: Raw schema from
                ``Model.model_json_schema()``.

        Returns:
            A new schema dict ready for ``response_format``.
        """

        schema = copy.deepcopy(schema)

        def _patch_object(obj: dict[str, Any]) -> None:
            """Add strict-mode keys to a single object schema."""
            if obj.get("type") == "object":
                obj["additionalProperties"] = False
                props = obj.get("properties", {})
                obj["required"] = list(props.keys())
                for prop in props.values():
                    _patch_object(prop)
                    # Handle anyOf / oneOf wrappers
                    for key in ("anyOf", "oneOf"):
                        for variant in prop.get(key, []):
                            _patch_object(variant)
            elif obj.get("type") == "array":
                items = obj.get("items", {})
                _patch_object(items)

        _patch_object(schema)
        for defn in schema.get("$defs", {}).values():
            _patch_object(defn)

        return schema

    def _build_options(
        self, max_tokens: int | None = None
    ) -> agent_framework.ChatOptions:
        """Build ``ChatOptions`` with optional structured output.

        Args:
            max_tokens: Override for max response tokens.

        Returns:
            Configured ``ChatOptions`` instance.
        """
        response_format: dict[str, Any] | None = None
        if self.response_model is not None:
            raw_schema = self.response_model.model_json_schema()
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": self.response_model.__name__,
                    "strict": True,
                    "schema": self._prepare_strict_schema(
                        raw_schema
                    ),
                },
            }
        return agent_framework.ChatOptions(
            max_tokens=max_tokens or self.max_tokens,
            response_format=response_format,
        )

    def _build_agent(
        self,
        instructions: str | None = None,
        max_tokens: int | None = None,
    ) -> agent_framework.ChatAgent:
        """Build a ``ChatAgent`` with middleware and options.

        The returned agent must be used as an async context
        manager (``async with``).

        Args:
            instructions: Override system prompt. Defaults to
                ``self.instructions``.
            max_tokens: Override max tokens.

        Returns:
            A ``ChatAgent`` ready for ``async with``.
        """
        if self._chat_client is None:
            raise ValueError(
                f"{self.agent_name}: chat client not"
                " initialised. Call initialise() first."
            )

        return agent_framework.ChatAgent(
            chat_client=self._chat_client,
            instructions=instructions or self.instructions,
            name=self.agent_name,
            description=(
                f"Chat agent for {self.agent_name}"
            ),
            tools=[],
            default_options=self._build_options(max_tokens),
            middleware=[self._retry, self._timing],
        )

    # ── Convenience helpers ─────────────────────────────────────

    async def _complete(
        self,
        user_prompt: str,
        *,
        instructions: str | None = None,
        max_tokens: int | None = None,
    ) -> agent_framework.AgentResponse:
        """Run a text-only completion and return the raw response.

        Args:
            user_prompt: User message content.
            instructions: Override system prompt.
            max_tokens: Override max tokens.

        Returns:
            The ``AgentResponse`` from the agent.
        """
        log.debug(
            f"{self.agent_name}: text completion",
            {"promptChars": len(user_prompt), "maxTokens": max_tokens or self.max_tokens},
        )
        message = agent_framework.ChatMessage(
            role=agent_framework.Role.USER,
            text=user_prompt,
        )
        async with self._build_agent(
            instructions, max_tokens
        ) as agent:
            response = await agent.run(message)
        log.debug(
            f"{self.agent_name}: response received",
            {"responseChars": len(response.text) if response.text else 0},
        )
        return response

    async def _complete_vision(
        self,
        user_text: str,
        screenshot: bytes,
        *,
        instructions: str | None = None,
        max_tokens: int | None = None,
    ) -> agent_framework.AgentResponse:
        """Run a vision completion and return the raw response.

        Base64 encoding is performed once before the call.

        Args:
            user_text: Textual part of the user message.
            screenshot: Raw screenshot bytes (PNG).
            instructions: Override system prompt.
            max_tokens: Override max tokens.

        Returns:
            The ``AgentResponse`` from the agent.
        """
        # Convert PNG to JPEG for a much smaller payload
        # (typically 5-10x reduction).

        img = Image.open(io.BytesIO(screenshot))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        jpeg_buf = io.BytesIO()
        img.save(jpeg_buf, format="JPEG", quality=72, optimize=True)
        jpeg_bytes = jpeg_buf.getvalue()

        b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
        image_uri = f"data:image/jpeg;base64,{b64}"
        log.debug(
            f"{self.agent_name}: vision completion",
            {
                "textChars": len(user_text),
                "pngBytes": len(screenshot),
                "jpegBytes": len(jpeg_bytes),
                "base64Chars": len(b64),
                "maxTokens": max_tokens or self.max_tokens,
            },
        )

        message = agent_framework.ChatMessage(
            role=agent_framework.Role.USER,
            contents=[
                agent_framework.Content.from_uri(
                    image_uri, media_type="image/jpeg"
                ),
                agent_framework.Content.from_text(user_text),
            ],
        )
        async with self._build_agent(
            instructions, max_tokens
        ) as agent:
            response = await agent.run(message)
        log.debug(
            f"{self.agent_name}: vision response received",
            {"responseChars": len(response.text) if response.text else 0},
        )
        return response

    def _parse_response(
        self,
        response: agent_framework.AgentResponse,
        model: type[T],
    ) -> T | None:
        """Attempt to parse a response into a Pydantic model.

        Falls back to ``None`` if parsing fails.

        Args:
            response: The agent response to parse.
            model: Target Pydantic model type.

        Returns:
            Parsed model instance or ``None``.
        """
        try:
            return response.try_parse_value(model)
        except Exception as exc:
            log.warn(
                f"{self.agent_name}: failed to parse"
                f" structured output: {exc}",
                {"responsePreview": (response.text or "")[:200]},
            )
            return None

    @staticmethod
    def _load_json_from_text(text: str | None) -> Any:
        """Strip LLM markdown fences and parse JSON.

        .. deprecated::
            Use ``src.utils.json_parsing.load_json_from_text``
            directly instead.
        """
        warnings.warn(
            "BaseAgent._load_json_from_text is deprecated;"
            " use src.utils.json_parsing.load_json_from_text",
            DeprecationWarning,
            stacklevel=2,
        )

        return json_parsing.load_json_from_text(text)
