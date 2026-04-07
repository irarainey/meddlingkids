"""Base agent factory for domain-specific agents.

Provides shared infrastructure for creating agents with
consistent middleware, chat client, and structured output
configuration.  Each domain agent subclasses ``BaseAgent``
and defines its own instructions and response format.
"""

from __future__ import annotations

from typing import TypeVar

import agent_framework
import pydantic

from src.agents import config, llm_client
from src.agents import context_providers as ctx_providers
from src.agents import middleware as middleware_mod
from src.utils import image, logger

log = logger.create_logger("BaseAgent")

T = TypeVar("T", bound=pydantic.BaseModel)


class BaseAgent:
    """Base class for all domain-specific agents.

    Manages a shared ``SupportsChatGetResponse`` and constructs
    purpose-specific ``Agent`` contexts with timing and
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
    call_timeout: float = 30
    temperature: float | None = None
    seed: int | None = None
    response_model: type[pydantic.BaseModel] | None = None
    use_responses_api: bool = False

    def __init__(self) -> None:
        """Initialise with a shared LLM chat client."""
        self._chat_client: agent_framework.SupportsChatGetResponse | None = None
        self._fallback_client: agent_framework.SupportsChatGetResponse | None = None
        self._using_fallback = False
        self._deployment: str | None = None
        self._agent: agent_framework.Agent | None = None
        self._timing = middleware_mod.TimingChatMiddleware(self.agent_name)
        self._retry = middleware_mod.RetryChatMiddleware(
            self.agent_name,
            max_retries=self.max_retries,
            per_call_timeout=self.call_timeout,
        )

    def initialise(self) -> bool:
        """Create the underlying LLM chat client and build the reusable Agent.

        The MAF ``Agent`` is built once and reused across
        calls.  Per-call overrides (instructions,
        response_format, max_tokens) are passed via
        ``agent.run(options=...)``.

        When the agent's name has a deployment override
        configured via ``config.get_agent_deployment()``,
        a dedicated client using that deployment is created
        and a fallback client using the default deployment
        is also prepared.  If the override model fails at
        runtime with a non-retryable error, the agent
        switches to the fallback transparently.

        Returns:
            ``True`` when the client was created.
        """
        deployment = config.get_agent_deployment(self.agent_name)
        self._deployment = deployment
        self._chat_client = llm_client.get_chat_client(
            agent_name=self.agent_name,
            deployment_override=deployment,
            use_responses_api=self.use_responses_api if deployment else False,
        )
        # When using a deployment override, also prepare a
        # fallback client on the default deployment so the
        # agent can recover if the override model is
        # unsupported.
        if deployment and self._chat_client is not None:
            self._fallback_client = llm_client.get_chat_client(
                agent_name=self.agent_name,
            )

        if self._chat_client is not None:
            self._agent = self._create_agent(self._chat_client)

        return self._chat_client is not None

    @property
    def is_configured(self) -> bool:
        """Whether the LLM client is ready."""
        return self._chat_client is not None

    @property
    def has_fallback(self) -> bool:
        """Whether a fallback client is available."""
        return self._fallback_client is not None and not self._using_fallback

    def activate_fallback(self) -> bool:
        """Switch to the fallback client and rebuild the agent.

        Called when the primary (override) deployment
        returns a non-retryable error such as
        ``OperationNotSupported``.

        Returns:
            ``True`` when the fallback was activated.
        """
        if not self.has_fallback:
            return False
        log.warn(
            f"{self.agent_name}: switching to fallback (default deployment)",
        )
        self._chat_client = self._fallback_client
        self._fallback_client = None
        self._using_fallback = True
        assert self._chat_client is not None  # guaranteed by has_fallback check
        self._agent = self._create_agent(self._chat_client)
        return True

    # ── Agent construction ──────────────────────────────────────

    def _build_options(
        self,
        max_tokens: int | None = None,
        response_model: type[pydantic.BaseModel] | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> agent_framework.ChatOptions:
        """Build ``ChatOptions`` with optional structured output.

        Passes the Pydantic model class directly to
        ``response_format`` — the MAF + OpenAI SDK handles
        strict-mode schema conversion automatically.

        Args:
            max_tokens: Override for max response tokens.
            response_model: Override response model for
                structured output. Falls back to
                ``self.response_model`` when ``None``.
            temperature: Override LLM temperature.
            seed: Override deterministic seed.

        Returns:
            Configured ``ChatOptions`` instance.
        """
        model = response_model or self.response_model

        opts = agent_framework.ChatOptions(
            max_tokens=max_tokens or self.max_tokens,
        )
        if model is not None:
            opts["response_format"] = model  # type: ignore[typeddict-item]

        effective_temp = temperature if temperature is not None else self.temperature
        if effective_temp is not None:
            opts["temperature"] = effective_temp

        effective_seed = seed if seed is not None else self.seed
        if effective_seed is not None:
            opts["seed"] = effective_seed

        return opts

    def _create_agent(
        self,
        client: agent_framework.SupportsChatGetResponse,
    ) -> agent_framework.Agent:
        """Build a reusable ``Agent`` with middleware and default options.

        The agent is created once and stored on the instance.
        Per-call overrides (instructions, response_format,
        max_tokens) are passed via ``agent.run(options=...)``.

        Includes the ``GdprReferenceProvider`` so agents can
        opt into GDPR/TCF context injection by setting
        ``session.state["gdpr-reference"]["gdpr_context_enabled"] = True``
        before calling ``agent.run()``.

        Args:
            client: The chat client to use.

        Returns:
            A configured ``Agent`` instance.
        """
        return agent_framework.Agent(
            client=client,
            instructions=self.instructions or None,
            name=self.agent_name,
            description=f"Chat agent for {self.agent_name}",
            tools=[],
            default_options=self._build_options(),
            middleware=[self._retry, self._timing],
            context_providers=[ctx_providers.GdprReferenceProvider()],
        )

    # ── Convenience helpers ─────────────────────────────────────

    async def _complete(
        self,
        user_prompt: str,
        *,
        instructions: str | None = None,
        max_tokens: int | None = None,
        response_model: type[pydantic.BaseModel] | None = None,
    ) -> agent_framework.AgentResponse:
        """Run a text-only completion and return the raw response.

        Reuses the pre-built ``Agent`` instance, passing
        per-call overrides via ``options``.

        Args:
            user_prompt: User message content.
            instructions: Override system prompt.
            max_tokens: Override max tokens.
            response_model: Override response model for
                structured output.

        Returns:
            The ``AgentResponse`` from the agent.
        """
        if self._agent is None:
            raise ValueError(f"{self.agent_name}: agent not initialised. Call initialise() first.")

        log.debug(
            f"{self.agent_name}: text completion",
            {"promptChars": len(user_prompt), "maxTokens": max_tokens or self.max_tokens},
        )
        message = agent_framework.Message(
            role="user",
            contents=[user_prompt],
        )

        # Build per-call options only for overrides.
        call_opts: agent_framework.ChatOptions | None = None
        if instructions is not None or max_tokens is not None or response_model is not None:
            call_opts = agent_framework.ChatOptions()
            if instructions is not None:
                call_opts["instructions"] = instructions
            if max_tokens is not None:
                call_opts["max_tokens"] = max_tokens
            if response_model is not None:
                call_opts["response_format"] = response_model  # type: ignore[typeddict-item]

        session = agent_framework.AgentSession()
        try:
            response = await self._agent.run(message, session=session, options=call_opts)
        finally:
            logger.save_agent_thread(self.agent_name, session.to_dict())
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

        Reuses the pre-built ``Agent`` instance.  Base64
        encoding is performed once before the call.

        Args:
            user_text: Textual part of the user message.
            screenshot: Raw JPEG screenshot bytes.
            instructions: Override system prompt.
            max_tokens: Override max tokens.

        Returns:
            The ``AgentResponse`` from the agent.
        """
        if self._agent is None:
            raise ValueError(f"{self.agent_name}: agent not initialised. Call initialise() first.")

        image_uri, jpeg_size = image.optimize_for_llm(screenshot)
        log.debug(
            f"{self.agent_name}: vision completion",
            {
                "textChars": len(user_text),
                "screenshotBytes": len(screenshot),
                "llmJpegBytes": jpeg_size,
                "maxTokens": max_tokens or self.max_tokens,
            },
        )

        message = agent_framework.Message(
            role="user",
            contents=[
                agent_framework.Content.from_uri(image_uri, media_type="image/jpeg"),
                agent_framework.Content.from_text(user_text),
            ],
        )

        call_opts: agent_framework.ChatOptions | None = None
        if instructions is not None or max_tokens is not None:
            call_opts = agent_framework.ChatOptions()
            if instructions is not None:
                call_opts["instructions"] = instructions
            if max_tokens is not None:
                call_opts["max_tokens"] = max_tokens

        session = agent_framework.AgentSession()
        try:
            response = await self._agent.run(message, session=session, options=call_opts)
        finally:
            logger.save_agent_thread(self.agent_name, session.to_dict())
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

        Tries ``response.value`` first (native MAF structured
        output parsing), then falls back to manual
        ``model.model_validate_json`` on ``response.text``.

        Falls back to ``None`` if parsing fails.

        Args:
            response: The agent response to parse.
            model: Target Pydantic model type.

        Returns:
            Parsed model instance or ``None``.
        """
        # Try native MAF structured output parsing first.
        try:
            val = response.value
            if val is not None and isinstance(val, model):
                return val
        except Exception:
            pass

        # Fallback: parse response.text directly.
        text = response.text
        if not text:
            log.warn(
                f"{self.agent_name}: empty response text — cannot parse",
            )
            return None
        try:
            return model.model_validate_json(text)
        except Exception as exc:
            log.warn(
                f"{self.agent_name}: failed to parse structured output: {exc}",
                {"responsePreview": text[:200]},
            )
            return None
