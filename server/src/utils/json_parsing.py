"""JSON parsing helpers for LLM response text."""

from __future__ import annotations

import json
import re
from typing import Any


def load_json_from_text(text: str | None) -> Any:
    """Strip LLM markdown fences and parse JSON.

    Handles ``````json ... `````` wrappers that models
    sometimes emit even when structured output is
    requested.

    Args:
        text: Raw LLM response text, possibly
            wrapped in code fences.

    Returns:
        Parsed JSON value, or ``None`` on failure.
    """
    content = (text or "").strip()
    if content.startswith("```"):
        content = re.sub(r"```json?\n?", "", content)
        content = re.sub(r"```\s*$", "", content).strip()
    try:
        return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None
