"""Shared data-loading helpers.

Provides path constants and JSON loading used by all data
sub-modules.  Kept small so that each feature-specific
loader can import from here without pulling in unrelated
data files.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from src.models import partners
from src.utils import logger

log = logger.create_logger("DataLoader")

# Resolve path to the data directory (same directory as this module)
_DATA_DIR = pathlib.Path(__file__).resolve().parent


def _load_json(relative_path: str) -> Any:
    """Load and parse a JSON file relative to the data directory.

    Raises:
        FileNotFoundError: If the JSON file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
        ValueError: If the path escapes the data directory.
    """
    full_path = (_DATA_DIR / relative_path).resolve()
    if not full_path.is_relative_to(_DATA_DIR):
        raise ValueError(f"Path escapes data directory: {relative_path}")
    if not full_path.exists():
        raise FileNotFoundError(f"Data file not found: {relative_path}")
    with open(full_path, encoding="utf-8") as f:
        try:
            data = json.load(f)
            log.debug("Loaded data file", {"file": relative_path})
            return data
        except json.JSONDecodeError as exc:
            log.error(
                "Invalid JSON in data file",
                {"file": relative_path, "error": exc.msg},
            )
            raise json.JSONDecodeError(
                f"Invalid JSON in {relative_path}: {exc.msg}",
                exc.doc,
                exc.pos,
            ) from exc


def _load_script_patterns(filename: str) -> list[partners.ScriptPattern]:
    """Load script patterns from a JSON file.

    Compiles each regex once at load time so that
    matching is fast on every subsequent call.
    """
    raw: list[dict[str, str]] = _load_json(f"trackers/{filename}")
    patterns = [
        partners.ScriptPattern(
            pattern=entry["pattern"],
            description=entry["description"],
            compiled=re.compile(entry["pattern"], re.IGNORECASE),
        )
        for entry in raw
    ]
    log.info("Script patterns compiled", {"file": filename, "count": len(patterns)})
    return patterns
