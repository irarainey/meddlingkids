"""
Logging utility with timestamps and timing support.
Provides structured, colourful console output for tracking analysis stages.
Optionally writes logs to a timestamped file when WRITE_LOG_TO_FILE is set.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ============================================================================
# Timer storage
# ============================================================================

_timers: dict[str, float] = {}

# ============================================================================
# File Logging
# ============================================================================

_write_to_file = os.environ.get("WRITE_LOG_TO_FILE", "").lower() == "true"
_log_file_stream: object | None = None
_log_file_path: str | None = None


def start_log_file(domain: str) -> None:
    """Start a new log file for a specific analysis."""
    global _log_file_stream, _log_file_path

    if not _write_to_file:
        return

    if _log_file_stream is not None:
        try:
            _log_file_stream.close()  # type: ignore[union-attr]
        except Exception:
            pass
        _log_file_stream = None

    logs_dir = Path.cwd() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    safe_domain = domain.lstrip("www.")
    safe_domain = "".join(c if c.isalnum() or c in ".-" else "_" for c in safe_domain)[:50]

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    _log_file_path = str(logs_dir / f"{safe_domain}_{timestamp}.log")

    _log_file_stream = open(_log_file_path, "a", encoding="utf-8")  # noqa: SIM115

    header = (
        f"\n{'=' * 80}\n"
        f"  Analysis Log - {domain}\n"
        f"  Started: {now.isoformat()}\n"
        f"{'=' * 80}\n"
    )
    _log_file_stream.write(header)  # type: ignore[union-attr]
    print(f"\033[36mℹ [Logger] Writing logs to: {_log_file_path}\033[0m")


def _write_to_log_file(line: str) -> None:
    """Write a line to the log file (without ANSI colours)."""
    if _log_file_stream is None:
        return
    import re

    clean = re.sub(r"\033\[[0-9;]*m", "", line)
    _log_file_stream.write(clean + "\n")  # type: ignore[union-attr]


# ============================================================================
# ANSI Colours
# ============================================================================

_colours = {
    "reset": "\033[0m",
    "bright": "\033[1m",
    "dim": "\033[2m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "magenta": "\033[35m",
    "blue": "\033[34m",
    "gray": "\033[90m",
}

_level_colour = {
    "info": _colours["cyan"],
    "success": _colours["green"],
    "warn": _colours["yellow"],
    "error": _colours["red"],
    "debug": _colours["gray"],
    "timing": _colours["magenta"],
}

_level_symbol = {
    "info": "ℹ",
    "success": "✓",
    "warn": "⚠",
    "error": "✗",
    "debug": "•",
    "timing": "⏱",
}


def _get_timestamp() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def _format_duration(ms: float) -> str:
    if ms < 1000:
        return f"{int(ms)}ms"
    if ms < 60000:
        return f"{ms / 1000:.2f}s"
    minutes = int(ms // 60000)
    seconds = (ms % 60000) / 1000
    return f"{minutes}m {seconds:.1f}s"


def _format_value(value: object) -> str:
    c = _colours
    if value is None:
        return f"{c['dim']}null{c['reset']}"
    if isinstance(value, bool):
        return f"{c['green']}true{c['reset']}" if value else f"{c['red']}false{c['reset']}"
    if isinstance(value, (int, float)):
        return f"{c['yellow']}{value}{c['reset']}"
    if isinstance(value, str):
        display = value[:497] + "..." if len(value) > 500 else value
        return f'{c["green"]}"{display}"{c["reset"]}'
    if isinstance(value, list):
        return f"{c['cyan']}[{len(value)} items]{c['reset']}"
    if isinstance(value, dict):
        return f"{c['cyan']}{{{len(value)} keys}}{c['reset']}"
    return str(value)


# ============================================================================
# Logger Class
# ============================================================================


class Logger:
    """Structured logger with context prefix and timing support."""

    def __init__(self, context: str = "Server") -> None:
        self._context = context

    def child(self, context: str) -> Logger:
        return Logger(context)

    def _log(self, level: str, message: str, data: dict[str, object] | None = None) -> None:
        ts = _get_timestamp()
        colour = _level_colour.get(level, _colours["cyan"])
        symbol = _level_symbol.get(level, "ℹ")
        c = _colours

        prefix = f"{c['gray']}[{ts}]{c['reset']} {colour}{symbol}{c['reset']} {c['bright']}[{self._context}]{c['reset']}"

        if data:
            data_str = " ".join(
                f"{c['dim']}{k}={c['reset']}{_format_value(v)}" for k, v in data.items()
            )
            log_line = f"{prefix} {message} {data_str}"
        else:
            log_line = f"{prefix} {message}"

        print(log_line, file=sys.stderr)
        _write_to_log_file(log_line)

    def info(self, message: str, data: dict[str, object] | None = None) -> None:
        self._log("info", message, data)

    def success(self, message: str, data: dict[str, object] | None = None) -> None:
        self._log("success", message, data)

    def warn(self, message: str, data: dict[str, object] | None = None) -> None:
        self._log("warn", message, data)

    def error(self, message: str, data: dict[str, object] | None = None) -> None:
        self._log("error", message, data)

    def debug(self, message: str, data: dict[str, object] | None = None) -> None:
        self._log("debug", message, data)

    def start_timer(self, label: str) -> None:
        key = f"{self._context}:{label}"
        _timers[key] = time.monotonic() * 1000
        self._log("timing", f"Starting: {label}")

    def end_timer(self, label: str, message: str | None = None) -> float:
        key = f"{self._context}:{label}"
        start = _timers.pop(key, None)
        if start is None:
            self.warn(f'Timer "{label}" was not started')
            return 0.0

        duration = time.monotonic() * 1000 - start
        c = _colours
        duration_str = f"{c['magenta']}{_format_duration(duration)}{c['reset']}"
        display_message = message or f"Completed: {label}"
        self._log("timing", f"{display_message} {c['dim']}took{c['reset']} {duration_str}")
        return duration

    def section(self, title: str) -> None:
        c = _colours
        line = "─" * 60
        lines = [
            "",
            f"{c['blue']}{line}{c['reset']}",
            f"{c['blue']}{c['bright']}  {title}{c['reset']}",
            f"{c['blue']}{line}{c['reset']}",
            "",
        ]
        for ln in lines:
            print(ln, file=sys.stderr)
            _write_to_log_file(ln)

    def subsection(self, title: str) -> None:
        c = _colours
        output = f"\n{c['cyan']}  ▸ {title}{c['reset']}"
        print(output, file=sys.stderr)
        _write_to_log_file(output)


def create_logger(context: str) -> Logger:
    """Create a logger for a specific module."""
    return Logger(context)
