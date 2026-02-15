"""
Logging utility with timestamps and timing support.
Provides structured, colourful console output for tracking analysis stages.
Optionally writes logs to a timestamped file when WRITE_TO_FILE is set.

All mutable per-session state (timers, log buffer, log-file handle)
is stored in ``contextvars.ContextVar`` so that concurrent async
analysis tasks do not interfere with each other.
"""

from __future__ import annotations

import contextvars
import io
import os
import pathlib
import re
import sys
import time
from datetime import UTC, datetime

# ============================================================================
# Per-session state (isolated via contextvars)
# ============================================================================

_timers_var: contextvars.ContextVar[dict[str, tuple[float, str]]] = contextvars.ContextVar("_timers_var")
_log_buffer_var: contextvars.ContextVar[list[str]] = contextvars.ContextVar("_log_buffer_var")
_log_file_stream_var: contextvars.ContextVar[io.TextIOWrapper | None] = contextvars.ContextVar("_log_file_stream_var", default=None)
_log_file_path_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("_log_file_path_var", default=None)


def _get_timers() -> dict[str, tuple[float, str]]:
    """Return the per-context timer dict, creating it on first access."""
    try:
        return _timers_var.get()
    except LookupError:
        timers: dict[str, tuple[float, str]] = {}
        _timers_var.set(timers)
        return timers


def _get_log_buffer() -> list[str]:
    """Return the per-context log buffer, creating it on first access."""
    try:
        return _log_buffer_var.get()
    except LookupError:
        buf: list[str] = []
        _log_buffer_var.set(buf)
        return buf


def get_log_buffer() -> list[str]:
    """Return a copy of the accumulated log lines (ANSI-stripped)."""
    return list(_get_log_buffer())


def clear_log_buffer() -> None:
    """Clear the in-memory log buffer and timers for the next analysis run."""
    _get_log_buffer().clear()
    _get_timers().clear()


# ============================================================================
# File Logging
# ============================================================================

_write_to_file = os.environ.get("WRITE_TO_FILE", "").lower() == "true"


def start_log_file(domain: str) -> None:
    """Start a new log file for a specific analysis."""
    if not _write_to_file:
        return

    end_log_file()

    logs_dir = pathlib.Path.cwd() / ".logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    safe_domain = domain.removeprefix("www.")
    safe_domain = "".join(c if c.isalnum() or c in ".-" else "_" for c in safe_domain)[:50]

    now = datetime.now(UTC)
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    log_file_path = str(logs_dir / f"{safe_domain}_{timestamp}.log")

    try:
        stream = open(log_file_path, "a", encoding="utf-8")  # noqa: SIM115
    except OSError as exc:
        print(f"\033[31m✗ [Logger] Failed to open log file: {exc}\033[0m")
        return

    _log_file_stream_var.set(stream)
    _log_file_path_var.set(log_file_path)

    header = f"\n{'=' * 80}\n  Analysis Log - {domain}\n  Started: {now.isoformat()}\n{'=' * 80}\n"
    stream.write(header)
    print(f"\033[36mℹ [Logger] Writing logs to: {log_file_path}\033[0m")


def end_log_file() -> None:
    """Flush and close the current log file."""
    stream = _log_file_stream_var.get(None)
    if stream is not None:
        try:
            stream.flush()
            stream.close()
        except Exception:
            print("\033[33m⚠ [Logger] Failed to flush/close log file stream\033[0m")
        _log_file_stream_var.set(None)
        _log_file_path_var.set(None)


def save_report_file(
    domain: str,
    report_text: str,
) -> str | None:
    """Save the final structured report as a text file.

    Only writes when ``WRITE_TO_FILE`` is enabled.

    Args:
        domain: The analysed domain (used in filename).
        report_text: Rendered report content.

    Returns:
        The file path written, or ``None`` if skipped.
    """
    if not _write_to_file:
        return None

    reports_dir = pathlib.Path.cwd() / ".reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    safe_domain = domain.removeprefix("www.")
    safe_domain = "".join(c if c.isalnum() or c in ".-" else "_" for c in safe_domain)[:50]

    now = datetime.now(UTC)
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    path = reports_dir / f"{safe_domain}_{timestamp}.txt"

    try:
        path.write_text(report_text, encoding="utf-8")
        print(f"\033[36m\u2139 [Logger] Report saved to: {path}\033[0m")
        return str(path)
    except Exception as err:
        print(f"\033[31m\u2717 [Logger] Failed to save report: {err}\033[0m")
        return None


def _write_to_log_file(line: str) -> None:
    """Write a line to the log file (without ANSI colours)."""
    stream = _log_file_stream_var.get(None)
    if stream is None:
        return

    clean = re.sub(r"\033\[[0-9;]*m", "", line)
    stream.write(clean + "\n")
    stream.flush()


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
    """Return the current UTC time as HH:MM:SS.mmm."""
    now = datetime.now(UTC)
    return now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def _format_duration(ms: float) -> str:
    """Format a duration in milliseconds for display."""
    if ms < 1000:
        return f"{int(ms)}ms"
    if ms < 60000:
        return f"{ms / 1000:.2f}s"
    minutes = int(ms // 60000)
    seconds = (ms % 60000) / 1000
    return f"{minutes}m {seconds:.1f}s"


def _format_value(value: object) -> str:
    """Return an ANSI-coloured representation of *value*."""
    c = _colours
    if value is None:
        return f"{c['dim']}None{c['reset']}"
    if isinstance(value, bool):
        return f"{c['green']}True{c['reset']}" if value else f"{c['red']}False{c['reset']}"
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
        """Create a logger that prefixes messages with *context*."""
        self._context = context

    def _log(self, level: str, message: str, data: dict[str, object] | None = None) -> None:
        """Format and emit a log line at the given level."""
        ts = _get_timestamp()
        colour = _level_colour.get(level, _colours["cyan"])
        symbol = _level_symbol.get(level, "ℹ")
        c = _colours

        prefix = f"{c['gray']}[{ts}]{c['reset']} {colour}{symbol}{c['reset']} {c['bright']}[{self._context}]{c['reset']}"

        if data:
            data_str = " ".join(f"{c['dim']}{k}={c['reset']}{_format_value(v)}" for k, v in data.items())
            log_line = f"{prefix} {message} {data_str}"
        else:
            log_line = f"{prefix} {message}"

        print(log_line, file=sys.stderr)
        _write_to_log_file(log_line)
        # Keep an ANSI-stripped copy for the client debug tab.
        _get_log_buffer().append(re.sub(r"\033\[[0-9;]*m", "", log_line))

    def info(self, message: str, data: dict[str, object] | None = None) -> None:
        """Log an informational message."""
        self._log("info", message, data)

    def success(self, message: str, data: dict[str, object] | None = None) -> None:
        """Log a success message."""
        self._log("success", message, data)

    def warn(self, message: str, data: dict[str, object] | None = None) -> None:
        """Log a warning message."""
        self._log("warn", message, data)

    def error(self, message: str, data: dict[str, object] | None = None) -> None:
        """Log an error message."""
        self._log("error", message, data)

    def debug(self, message: str, data: dict[str, object] | None = None) -> None:
        """Log a debug-level message."""
        self._log("debug", message, data)

    def start_timer(self, label: str) -> None:
        """Start a named timer for performance measurement."""
        key = f"{self._context}:{label}"
        _get_timers()[key] = (time.monotonic() * 1000, _get_timestamp())
        self._log("timing", f"Starting: {label}")

    def end_timer(self, label: str, message: str | None = None) -> float:
        """Stop a named timer and log the elapsed time."""
        key = f"{self._context}:{label}"
        entry = _get_timers().pop(key, None)
        if entry is None:
            self.warn(f'Timer "{label}" was not started')
            return 0.0

        start_ms, start_ts = entry
        duration = time.monotonic() * 1000 - start_ms
        c = _colours
        duration_str = f"{c['magenta']}{_format_duration(duration)}{c['reset']}"
        display_message = message or f"Completed: {label}"
        self._log(
            "timing",
            f"{display_message} {c['dim']}took{c['reset']} {duration_str} {c['dim']}(started {start_ts}){c['reset']}",
        )
        return duration

    def section(self, title: str) -> None:
        """Print a prominent section divider with *title*."""
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
            _get_log_buffer().append(re.sub(r"\033\[[0-9;]*m", "", ln))

    def subsection(self, title: str) -> None:
        """Print a smaller sub-section header."""
        c = _colours
        output = f"\n{c['cyan']}  ▸ {title}{c['reset']}"
        print(output, file=sys.stderr)
        _write_to_log_file(output)
        _get_log_buffer().append(re.sub(r"\033\[[0-9;]*m", "", output))


def create_logger(context: str) -> Logger:
    """Create a logger for a specific module."""
    return Logger(context)
