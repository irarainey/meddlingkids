"""Chat agent service for LLM-based analysis.

Provides a single, reusable ``ChatAgentService`` that wraps the
Microsoft Agent Framework ``ChatAgent`` to handle all LLM
interactions — text completions and vision-based analysis.

This replaces direct OpenAI client usage throughout the server
with a clean, framework-level abstraction.  Retry logic wraps
only the agent ``.run()`` call, and middleware instances are
cached per agent name so they are reused across invocations.
"""

from __future__ import annotations

import base64

import agent_framework

from src.agents import llm_client
from src.agents.middleware import TimingChatMiddleware
from src.utils import logger, retry

log = logger.create_logger("ChatAgent")


class ChatAgentService:
    """Unified chat agent service for all LLM interactions.

    Manages a shared ``ChatClientProtocol`` instance and creates
    purpose-specific ``ChatAgent`` contexts to perform text and
    vision completions with automatic retry logic.

    Middleware instances are cached per agent name so they are
    created once and reused across calls.

    Usage::

        service = ChatAgentService()
        service.initialise()

        result = await service.complete(
            system_prompt="You are a ...",
            user_prompt="Analyse this ...",
            agent_name=config.AGENT_TRACKING_ANALYSIS,
            max_tokens=3000,
        )
    """

    def __init__(self) -> None:
        """Initialise the service (call ``initialise()`` to set up)."""
        self._chat_client: agent_framework.ChatClientProtocol | None = (
            None
        )
        self._middleware: dict[str, TimingChatMiddleware] = {}

    def initialise(self) -> bool:
        """Create the underlying LLM chat client.

        Returns:
            ``True`` if the client was created successfully.
        """
        self._chat_client = llm_client.get_chat_client(
            agent_name="ChatAgentService"
        )
        return self._chat_client is not None

    @property
    def is_configured(self) -> bool:
        """Check whether the LLM client is ready.

        Returns:
            ``True`` when initialised and configured.
        """
        return self._chat_client is not None

    # ── Text completion ─────────────────────────────────────────────

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        agent_name: str = "ChatAgent",
        max_tokens: int = 3000,
        retry_context: str | None = None,
        max_retries: int = 3,
    ) -> str:
        """Run a text-only chat completion with retry.

        Creates a ``ChatAgent`` with the given instructions and
        retries only the ``.run()`` call on transient failures.

        Args:
            system_prompt: System instructions for the LLM.
            user_prompt: User message content.
            agent_name: Descriptive name for logging/tracing.
            max_tokens: Maximum response tokens.
            retry_context: Label for retry log messages.
            max_retries: Number of retry attempts.

        Returns:
            The assistant's response text.

        Raises:
            ValueError: When the chat client is not initialised.
            Exception: Propagated from the LLM after retries
                       are exhausted.
        """
        self._ensure_client()

        user_message = agent_framework.ChatMessage(
            role=agent_framework.Role.USER,
            text=user_prompt,
        )

        async with self._build_agent(
            system_prompt, agent_name, max_tokens
        ) as chat_agent:

            async def _invoke() -> str:
                result = await chat_agent.run(user_message)
                return result.text or ""

            return await retry.with_retry(
                _invoke,
                context=retry_context or agent_name,
                max_retries=max_retries,
            )

    # ── Vision completion ───────────────────────────────────────────

    async def complete_with_vision(
        self,
        system_prompt: str,
        user_text: str,
        screenshot: bytes,
        *,
        agent_name: str = "VisionAgent",
        max_tokens: int = 500,
        retry_context: str | None = None,
        max_retries: int = 3,
    ) -> str:
        """Run a vision chat completion with retry.

        Sends a screenshot image alongside a text prompt for
        multi-modal analysis.  Base64 encoding is performed once
        before the retry loop to avoid redundant work on retries.

        Args:
            system_prompt: System instructions for the LLM.
            user_text: Textual part of the user message.
            screenshot: Raw screenshot bytes (PNG).
            agent_name: Descriptive name for logging/tracing.
            max_tokens: Maximum response tokens.
            retry_context: Label for retry log messages.
            max_retries: Number of retry attempts.

        Returns:
            The assistant's response text.

        Raises:
            ValueError: When the chat client is not initialised.
            Exception: Propagated from the LLM after retries
                       are exhausted.
        """
        self._ensure_client()

        # Encode once — no need to repeat on retry.
        b64_screenshot = base64.b64encode(screenshot).decode("utf-8")
        image_uri = f"data:image/png;base64,{b64_screenshot}"

        user_message = agent_framework.ChatMessage(
            role=agent_framework.Role.USER,
            contents=[
                agent_framework.Content.from_uri(
                    image_uri, media_type="image/png"
                ),
                agent_framework.Content.from_text(user_text),
            ],
        )

        async with self._build_agent(
            system_prompt, agent_name, max_tokens
        ) as chat_agent:

            async def _invoke() -> str:
                result = await chat_agent.run(user_message)
                return result.text or ""

            return await retry.with_retry(
                _invoke,
                context=retry_context or agent_name,
                max_retries=max_retries,
            )

    # ── Internal helpers ────────────────────────────────────────────

    def _build_agent(
        self,
        instructions: str,
        agent_name: str,
        max_tokens: int,
    ) -> agent_framework.ChatAgent:
        """Build a ``ChatAgent`` with cached middleware.

        The returned agent must be used as an async context
        manager (``async with``).

        Args:
            instructions: System prompt / instructions.
            agent_name: Agent name for middleware logging.
            max_tokens: Maximum response tokens.

        Returns:
            A ``ChatAgent`` ready for ``async with``.
        """
        assert self._chat_client is not None  # noqa: S101

        return agent_framework.ChatAgent(
            chat_client=self._chat_client,
            instructions=instructions,
            name=agent_name,
            description=f"Chat agent for {agent_name}",
            tools=[],
            default_options=agent_framework.ChatOptions(
                max_tokens=max_tokens,
            ),
            middleware=[
                self._get_middleware(agent_name),
            ],
        )

    def _get_middleware(
        self, agent_name: str
    ) -> TimingChatMiddleware:
        """Get or create a cached middleware instance.

        Middleware is created once per agent name and reused
        across subsequent calls.

        Args:
            agent_name: Name of the agent for logging context.

        Returns:
            A reusable ``TimingChatMiddleware`` instance.
        """
        if agent_name not in self._middleware:
            self._middleware[agent_name] = TimingChatMiddleware(
                agent_name
            )
        return self._middleware[agent_name]

    def _ensure_client(self) -> None:
        """Raise if the chat client has not been initialised.

        Raises:
            ValueError: When ``initialise()`` has not been called
                        or returned ``False``.
        """
        if self._chat_client is None:
            raise ValueError(
                "Chat client is not initialised."
                " Call initialise() first."
            )


# ── Module-level singleton ──────────────────────────────────────────

_instance: ChatAgentService | None = None


def get_chat_agent_service() -> ChatAgentService:
    """Get or create the global ``ChatAgentService`` singleton.

    Returns:
        The shared ``ChatAgentService`` instance.  It will be
        automatically initialised on first access.
    """
    global _instance

    if _instance is None:
        _instance = ChatAgentService()
        if not _instance.initialise():
            log.warn(
                "ChatAgentService created but LLM is not"
                " configured. All agent calls will fail"
                " until configuration is set."
            )

    return _instance
