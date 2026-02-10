"""
Retry utility with exponential backoff for handling transient failures.
Particularly useful for handling rate limits (429) from OpenAI APIs.
"""

from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable, TypeVar

from src.utils import logger

log = logger.create_logger("Retry")

T = TypeVar("T")


def _is_rate_limit_error(error: BaseException) -> bool:
    """Check if the error is a rate limit (429) error."""
    err_str = str(error)
    if "429" in err_str or "rate limit" in err_str.lower():
        return True
    if hasattr(error, "status") and getattr(error, "status") == 429:
        return True
    if hasattr(error, "status_code") and getattr(error, "status_code") == 429:
        return True
    return False


def _is_retryable_error(error: BaseException) -> bool:
    """Check if the error is retryable (rate limit or server error)."""
    if _is_rate_limit_error(error):
        return True
    if hasattr(error, "status"):
        status = getattr(error, "status")
        if isinstance(status, int) and 500 <= status < 600:
            return True
    if hasattr(error, "status_code"):
        status = getattr(error, "status_code")
        if isinstance(status, int) and 500 <= status < 600:
            return True
    # Connection errors
    err_class = type(error).__name__
    if err_class in ("ConnectionError", "TimeoutError", "ConnectionResetError"):
        return True
    return False


def _get_retry_after_ms(error: BaseException) -> int | None:
    """Try to extract retry-after information from the error."""
    if hasattr(error, "headers"):
        headers = getattr(error, "headers", {})
        if isinstance(headers, dict):
            retry_after = headers.get("retry-after") or headers.get("Retry-After")
            if retry_after:
                try:
                    return int(retry_after) * 1000
                except (ValueError, TypeError):
                    pass
    return None


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 3,
    initial_delay_ms: int = 1000,
    max_delay_ms: int = 30000,
    backoff_multiplier: float = 2.0,
    context: str | None = None,
) -> T:
    """
    Execute an async function with automatic retry on transient failures.
    Uses exponential backoff with jitter for rate limit handling.
    """
    last_error: BaseException | None = None
    delay = initial_delay_ms

    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as error:
            last_error = error

            if not _is_retryable_error(error):
                raise

            if attempt >= max_retries:
                log.warn(
                    "All retry attempts exhausted",
                    {
                        "context": context,
                        "attempts": attempt + 1,
                        "error": str(error),
                    },
                )
                raise

            retry_after_ms = _get_retry_after_ms(error)
            actual_delay = retry_after_ms if retry_after_ms is not None else delay

            jitter = actual_delay * 0.2 * (random.random() * 2 - 1)
            delay_with_jitter = min(round(actual_delay + jitter), max_delay_ms)

            log.warn(
                "Retrying after transient error",
                {
                    "context": context,
                    "attempt": attempt + 1,
                    "maxRetries": max_retries,
                    "delayMs": delay_with_jitter,
                    "isRateLimit": _is_rate_limit_error(error),
                    "error": str(error)[:100],
                },
            )

            await asyncio.sleep(delay_with_jitter / 1000)
            delay = min(int(delay * backoff_multiplier), max_delay_ms)

    # Should never reach here, but satisfy type checker
    raise last_error  # type: ignore[misc]
