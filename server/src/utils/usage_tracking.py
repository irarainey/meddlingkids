"""Per-session LLM usage tracking.

Accumulates call counts and token usage across all agents
within a single analysis run.  State is stored in
``contextvars`` so concurrent async sessions are isolated.

Usage
-----
Call ``reset()`` at the start of each analysis run and
``log_summary()`` at the end.  Between those points, call
``record()`` after every LLM invocation (typically from
chat middleware) to keep a running tally.
"""

from __future__ import annotations

import contextvars
import dataclasses

from src.utils import logger

log = logger.create_logger("LLM-Usage")


@dataclasses.dataclass
class _SessionUsage:
    """Mutable accumulator for a single analysis session."""

    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0


_usage_var: contextvars.ContextVar[_SessionUsage] = contextvars.ContextVar("_usage_var")


def _get_usage() -> _SessionUsage:
    """Return the per-context usage tracker, creating it on first access."""
    try:
        return _usage_var.get()
    except LookupError:
        usage = _SessionUsage()
        _usage_var.set(usage)
        return usage


def reset() -> None:
    """Reset counters for a new analysis run."""
    _usage_var.set(_SessionUsage())


def record(
    agent_name: str,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
) -> None:
    """Record one LLM call and its token usage.

    Logs the per-call usage and the running session totals.

    Args:
        agent_name: Name of the agent that made the call.
        input_tokens: Prompt / input token count (if reported).
        output_tokens: Completion / output token count (if reported).
        total_tokens: Combined token count (if reported).
    """
    usage = _get_usage()
    usage.total_calls += 1

    call_input = input_tokens or 0
    call_output = output_tokens or 0
    call_total = total_tokens or (call_input + call_output)

    usage.total_input_tokens += call_input
    usage.total_output_tokens += call_output
    usage.total_tokens += call_total

    log.info(
        f"LLM call #{usage.total_calls} ({agent_name})",
        {
            "callTokens": call_total,
            "callInput": call_input,
            "callOutput": call_output,
            "runningCalls": usage.total_calls,
            "runningTokens": usage.total_tokens,
        },
    )


def log_summary() -> None:
    """Log the final usage summary for the completed analysis run."""
    usage = _get_usage()
    if usage.total_calls == 0:
        log.info("No LLM calls were made during this analysis")
        return

    log.info(
        "LLM usage summary",
        {
            "totalCalls": usage.total_calls,
            "totalInputTokens": usage.total_input_tokens,
            "totalOutputTokens": usage.total_output_tokens,
            "totalTokens": usage.total_tokens,
        },
    )
