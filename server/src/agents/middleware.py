"""
Chat middleware for agent-based analysis.

Provides timing middleware following the Microsoft Agent Framework
``ChatMiddleware`` pattern to measure and log LLM interaction
performance.
"""

from __future__ import annotations

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
            context: Chat invocation context with messages and options.
            next: Callable to invoke the next middleware or LLM call.
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
