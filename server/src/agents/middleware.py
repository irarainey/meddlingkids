"""Chat middleware for agent-based analysis.

Provides timing and retry middleware following the Microsoft Agent
Framework ``ChatMiddleware`` pattern.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable

import agent_framework

from src.utils import logger

log = logger.create_logger("Agent-Middleware")


class TimingChatMiddleware(agent_framework.ChatMiddleware):
    """Chat middleware that logs AI interaction timing.

    Captures start time before sending messages to the LLM,
    processes the request through the pipeline, and logs the
    elapsed duration for performance monitoring.

    Attributes:
        agent_name: Name of the agent using this middleware.
    """

    def __init__(self, agent_name: str | None = None) -> None:
        """Initialise the timing middleware.

        Args:
            agent_name: Name of the agent for logging context.
        """
        self.agent_name = agent_name or "Unknown"
        super().__init__()

    async def process(
        self,
        context: agent_framework.ChatContext,
        next: Callable[
            [agent_framework.ChatContext], Awaitable[None]
        ],
    ) -> None:
        """Process a chat request and measure execution time.

        Args:
            context: Chat invocation context with messages and
                options.
            next: Callable to invoke the next middleware or LLM.
        """
        message_count = len(context.messages)
        log.debug(
            f"Agent '{self.agent_name}' sending"
            f" {message_count} message(s) to LLM"
        )

        start_time = time.perf_counter()
        await next(context)
        duration = time.perf_counter() - start_time

        log.info(
            f"Agent '{self.agent_name}' completed in"
            f" {duration:.2f}s"
        )

        context.metadata["timing"] = {
            "duration_seconds": round(duration, 3),
            "agent_name": self.agent_name,
        }


# ── Retry constants ────────────────────────────────────────────────

_DEFAULT_MAX_RETRIES = 5
_DEFAULT_INITIAL_DELAY_MS = 1000
_DEFAULT_MAX_DELAY_MS = 30_000
_BACKOFF_MULTIPLIER = 2.0


def _is_retryable(error: BaseException) -> bool:
    """Check if an error is transient and worth retrying.

    Handles rate-limit (429) and server errors (5xx), as well
    as common connection-level failures.

    Args:
        error: The exception to inspect.

    Returns:
        ``True`` when the error is likely transient.
    """
    err_str = str(error).lower()
    if "429" in err_str or "rate limit" in err_str:
        return True
    for attr in ("status", "status_code"):
        code = getattr(error, attr, None)
        if isinstance(code, int):
            if code == 429 or 500 <= code < 600:
                return True
    err_class = type(error).__name__
    return err_class in (
        "ConnectionError",
        "TimeoutError",
        "ConnectionResetError",
    )


class RetryChatMiddleware(agent_framework.ChatMiddleware):
    """Chat middleware that retries LLM calls on transient failures.

    Uses exponential backoff with jitter.  Rate-limit ``Retry-After``
    headers are respected when present.

    Attributes:
        max_retries: Maximum number of retry attempts.
        initial_delay_ms: Initial delay before first retry.
        max_delay_ms: Cap on backoff delay.
        agent_name: Agent name for log context.
    """

    def __init__(
        self,
        agent_name: str | None = None,
        *,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        initial_delay_ms: int = _DEFAULT_INITIAL_DELAY_MS,
        max_delay_ms: int = _DEFAULT_MAX_DELAY_MS,
    ) -> None:
        """Initialise the retry middleware.

        Args:
            agent_name: Name of the agent for logging.
            max_retries: Maximum retry attempts.
            initial_delay_ms: First backoff delay in ms.
            max_delay_ms: Maximum backoff delay in ms.
        """
        self.agent_name = agent_name or "Unknown"
        self.max_retries = max_retries
        self.initial_delay_ms = initial_delay_ms
        self.max_delay_ms = max_delay_ms
        super().__init__()

    async def process(
        self,
        context: agent_framework.ChatContext,
        next: Callable[
            [agent_framework.ChatContext], Awaitable[None]
        ],
    ) -> None:
        """Invoke the LLM with automatic retry on failure.

        Args:
            context: Chat invocation context.
            next: Callable to invoke the next middleware or LLM.

        Raises:
            Exception: Re-raised from the last attempt when all
                retries are exhausted.
        """
        delay_ms = self.initial_delay_ms
        last_error: BaseException | None = None

        for attempt in range(self.max_retries + 1):
            try:
                await next(context)
                return
            except Exception as exc:
                last_error = exc
                if (
                    attempt >= self.max_retries
                    or not _is_retryable(exc)
                ):
                    if attempt >= self.max_retries:
                        log.error(
                            f"Agent '{self.agent_name}' exhausted all"
                            f" {self.max_retries + 1} attempts: {exc}"
                        )
                    raise

                # Respect Retry-After header when available.
                retry_after = self._get_retry_after(exc)
                wait_ms = retry_after or delay_ms
                jitter = random.uniform(0, wait_ms * 0.1)
                total_ms = min(
                    wait_ms + jitter, self.max_delay_ms
                )

                log.warn(
                    f"Agent '{self.agent_name}' attempt"
                    f" {attempt + 1}/{self.max_retries + 1}"
                    f" failed, retrying in"
                    f" {total_ms / 1000:.1f}s: {exc}"
                )
                await asyncio.sleep(total_ms / 1000)
                delay_ms = int(
                    delay_ms * _BACKOFF_MULTIPLIER
                )

        if last_error:  # pragma: no cover — defensive
            raise last_error

    @staticmethod
    def _get_retry_after(
        error: BaseException,
    ) -> int | None:
        """Extract ``Retry-After`` value from error headers.

        Args:
            error: The exception to inspect.

        Returns:
            Delay in milliseconds, or ``None``.
        """
        headers = getattr(error, "headers", None)
        if isinstance(headers, dict):
            raw = headers.get("retry-after") or headers.get(
                "Retry-After"
            )
            if raw:
                try:
                    return int(raw) * 1000
                except (ValueError, TypeError):
                    pass
        return None
