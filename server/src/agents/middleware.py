"""Chat middleware for agent-based analysis.

Provides timing and retry middleware following the Microsoft Agent
Framework ``ChatMiddleware`` pattern.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, cast

import agent_framework

from src.utils import logger, usage_tracking

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
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        """Process a chat request and measure execution time.

        Args:
            context: Chat invocation context with messages and
                options.
            call_next: Callable to invoke the next middleware or LLM.
        """
        message_count = len(context.messages)
        total_chars = _estimate_message_chars(context.messages)
        est_tokens = total_chars // 4
        log.info(
            f"Agent '{self.agent_name}' sending {message_count} message(s) (~{total_chars:,} chars, ~{est_tokens:,} est. tokens)",
        )

        start_time = time.perf_counter()
        await call_next()
        duration = time.perf_counter() - start_time

        response_meta = _describe_response(context.result)
        log.info(
            f"Agent '{self.agent_name}' completed in {duration:.2f}s — {response_meta}",
        )

        metadata = cast(dict[str, Any], context.metadata)
        metadata["timing"] = {
            "duration_seconds": round(duration, 3),
            "agent_name": self.agent_name,
        }

        # Record LLM token usage for the running session tally.
        self._record_usage(context)

    def _record_usage(self, context: agent_framework.ChatContext) -> None:
        """Extract token usage from the LLM response and record it.

        Args:
            context: Chat context after LLM invocation.
        """
        result = context.result
        if result is None:
            return

        usage = getattr(result, "usage_details", None)
        if usage is None:
            usage_tracking.record(self.agent_name)
            return

        usage_tracking.record(
            self.agent_name,
            input_tokens=usage.get("input_token_count"),
            output_tokens=usage.get("output_token_count"),
            total_tokens=usage.get("total_token_count"),
        )


# ── Retry constants ────────────────────────────────────────────────

_DEFAULT_MAX_RETRIES = 5
_DEFAULT_INITIAL_DELAY_MS = 1000
_DEFAULT_MAX_DELAY_MS = 30_000
_BACKOFF_MULTIPLIER = 2.0

# ── Global LLM concurrency ─────────────────────────────────────────

_MAX_CONCURRENT_LLM_CALLS = 10
"""Maximum LLM calls in-flight at once across all agents.

Prevents overwhelming the Azure OpenAI endpoint when
multiple agents (e.g. StructuredReportAgent 10 sections +
ScriptAnalysisAgent batch) fire concurrently.
"""

_llm_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_LLM_CALLS)


class EmptyResponseError(Exception):
    """Raised when the LLM returns an empty (zero-character) response.

    Treated as a transient failure so the retry middleware
    can re-attempt the request.
    """


class OutputTruncatedError(EmptyResponseError):
    """Raised when the LLM output was truncated by the token limit.

    This is a *deterministic* failure — the output needs more
    tokens than ``max_tokens`` allows — so retrying with the
    same prompt is pointless.  Not treated as retryable.
    """


def _estimate_message_chars(messages: Sequence[Any]) -> int:
    """Estimate total character count across all messages.

    Sums ``len(msg.text)`` for each message with a text
    attribute, providing a rough input-size approximation.

    Args:
        messages: List of agent framework message objects.

    Returns:
        Total character count.
    """
    total = 0
    for msg in messages:
        text = getattr(msg, "text", None)
        if text:
            total += len(text)
    return total


def _describe_response(result: object) -> str:
    """Build a short diagnostic string from an LLM response.

    Extracts ``finish_reason``, ``model_id``, and
    ``usage_details`` (input/output token counts) when
    available on the response object.

    Args:
        result: The ``ChatResponse`` or similar object
            returned by the agent framework.

    Returns:
        A formatted string such as
        ``finish_reason=length, model=gpt-5.2-chat,
        input_tokens=52630, output_tokens=2048``.
        Falls back to ``"(no metadata)"`` when nothing
        is available.
    """
    parts: list[str] = []

    finish = getattr(result, "finish_reason", None)
    if finish is not None:
        parts.append(f"finish_reason={finish}")

    model = getattr(result, "model_id", None)
    if model is not None:
        parts.append(f"model={model}")

    usage = getattr(result, "usage_details", None)
    if isinstance(usage, dict):
        inp = usage.get("input_token_count")
        out = usage.get("output_token_count")
        if inp is not None:
            parts.append(f"input_tokens={inp}")
        if out is not None:
            parts.append(f"output_tokens={out}")

    extra = getattr(result, "additional_properties", None)
    if extra:
        parts.append(f"extra={extra}")

    return ", ".join(parts) if parts else "(no metadata)"


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
    if "timed out" in err_str or "timeout" in err_str:
        return True
    for attr in ("status", "status_code"):
        code = getattr(error, attr, None)
        if isinstance(code, int) and (code == 429 or 500 <= code < 600):
            return True
    # OutputTruncatedError is a subclass of EmptyResponseError
    # but is deterministic (max_tokens too low), so exclude it.
    if isinstance(error, OutputTruncatedError):
        return False
    return isinstance(
        error,
        (
            ConnectionError,
            TimeoutError,
            EmptyResponseError,
        ),
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
        per_call_timeout: Seconds before a single LLM call
            is cancelled.  ``None`` disables the guard.
    """

    def __init__(
        self,
        agent_name: str | None = None,
        *,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        initial_delay_ms: int = _DEFAULT_INITIAL_DELAY_MS,
        max_delay_ms: int = _DEFAULT_MAX_DELAY_MS,
        per_call_timeout: float | None = None,
    ) -> None:
        """Initialise the retry middleware.

        Args:
            agent_name: Name of the agent for logging.
            max_retries: Maximum retry attempts.
            initial_delay_ms: First backoff delay in ms.
            max_delay_ms: Maximum backoff delay in ms.
            per_call_timeout: Seconds before an individual
                LLM call is cancelled.  ``None`` disables.
        """
        self.agent_name = agent_name or "Unknown"
        self.max_retries = max_retries
        self.initial_delay_ms = initial_delay_ms
        self.max_delay_ms = max_delay_ms
        self.per_call_timeout = per_call_timeout
        super().__init__()

    async def process(
        self,
        context: agent_framework.ChatContext,
        call_next: Callable[[], Awaitable[None]],
    ) -> None:
        """Invoke the LLM with automatic retry on failure.

        Args:
            context: Chat invocation context.
            call_next: Callable to invoke the next middleware or LLM.

        Raises:
            Exception: Re-raised from the last attempt when all
                retries are exhausted.
        """
        delay_ms = self.initial_delay_ms
        last_error: BaseException | None = None

        for attempt in range(self.max_retries + 1):
            try:
                async with _llm_semaphore:
                    if self.per_call_timeout is not None:
                        await asyncio.wait_for(
                            call_next(),
                            timeout=self.per_call_timeout,
                        )
                    else:
                        await call_next()
                self._check_empty_response(context)
                return
            except TimeoutError as exc:
                # asyncio.wait_for raises a bare TimeoutError
                # with no message — wrap with a descriptive one.
                last_error = TimeoutError(f"LLM call timed out after {self.per_call_timeout}s")
                if attempt >= self.max_retries:
                    log.error(f"Agent '{self.agent_name}' exhausted all {self.max_retries + 1} attempts: {last_error}")
                    raise last_error from exc

                delay_ms = await self._backoff_and_log(attempt, last_error, delay_ms)
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries or not _is_retryable(exc):
                    if attempt >= self.max_retries:
                        log.error(f"Agent '{self.agent_name}' exhausted all {self.max_retries + 1} attempts: {exc}")
                    raise

                delay_ms = await self._backoff_and_log(attempt, exc, delay_ms)

        if last_error:  # pragma: no cover — defensive
            raise last_error

    def _check_empty_response(self, context: agent_framework.ChatContext) -> None:
        """Raise ``EmptyResponseError`` when the LLM returns no text.

        An empty response is almost certainly a transient
        failure (model overload, content-filter false
        positive, etc.) and should be retried.

        Args:
            context: Chat context after LLM invocation.
        """
        result = context.result
        if result is None:
            return
        try:
            text = result.text  # type: ignore[union-attr]
        except Exception:
            return

        # Warn when the response was cut short by the token limit.
        finish = getattr(result, "finish_reason", None)
        if finish == "length":
            detail = _describe_response(result)
            log.warn(
                f"Agent '{self.agent_name}' response truncated (finish_reason=length) — {detail}",
            )

        if not text:
            detail = _describe_response(result)
            log.warn(
                f"Agent '{self.agent_name}' received an empty response from the LLM — {detail}",
            )
            # When finish_reason=length, the output was truncated
            # by the max_tokens ceiling.  With structured output
            # (response_format=json_schema) the API cannot return
            # partial JSON, so it returns empty text.  This is
            # deterministic — retrying won't help.
            if finish == "length":
                raise OutputTruncatedError(
                    f"Agent '{self.agent_name}' output exceeded max_tokens (response truncated with 0 usable characters) — {detail}",
                )
            raise EmptyResponseError(
                f"Agent '{self.agent_name}' received an empty (0-character) response — {detail}",
            )

    def _log_retry(
        self,
        attempt: int,
        exc: BaseException,
        total_ms: float,
    ) -> None:
        """Log a retry warning with attempt details.

        Args:
            attempt: Zero-based attempt index.
            exc: The exception that triggered the retry.
            total_ms: Actual delay (with jitter) to be slept.
        """
        log.warn(
            f"Agent '{self.agent_name}' attempt {attempt + 1}/{self.max_retries + 1} failed, retrying in {total_ms / 1000:.1f}s: {exc}"
        )

    async def _backoff_and_log(
        self,
        attempt: int,
        exc: BaseException,
        delay_ms: int,
    ) -> int:
        """Compute jitter once, log the delay, sleep, and return the next base delay.

        Respects ``Retry-After`` headers when present.

        Args:
            attempt: Zero-based attempt index.
            exc: The exception (may contain headers).
            delay_ms: Current base delay in ms.

        Returns:
            Updated base delay for the next attempt.
        """
        retry_after = self._get_retry_after(exc)
        wait_ms = retry_after or delay_ms
        jitter = random.uniform(0, wait_ms * 0.1)
        total_ms = min(wait_ms + jitter, self.max_delay_ms)
        self._log_retry(attempt, exc, total_ms)
        await asyncio.sleep(total_ms / 1000)
        return int(delay_ms * _BACKOFF_MULTIPLIER)

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
            raw = headers.get("retry-after") or headers.get("Retry-After")
            if raw:
                try:
                    return int(raw) * 1000
                except (ValueError, TypeError):
                    pass
        return None
