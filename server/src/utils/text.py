"""Shared text-processing utility functions.

Small helpers used across multiple modules to avoid
duplicating regex patterns or string transformations.
"""

from __future__ import annotations

import re

# Pre-compiled pattern for stripping ANSI escape sequences.
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Remove ANSI colour/style escape sequences from *text*.

    Args:
        text: A string that may contain ANSI SGR codes.

    Returns:
        The same string with all ``\\033[…m`` sequences removed.
    """
    return _ANSI_RE.sub("", text)


def sanitize_domain(domain: str, *, max_length: int = 50) -> str:
    """Convert a domain name into a filesystem-safe string.

    Strips the ``www.`` prefix, replaces non-alphanumeric
    characters (except ``.`` and ``-``) with underscores,
    and truncates to *max_length*.

    Args:
        domain: A hostname such as ``"www.example.co.uk"``.
        max_length: Maximum characters in the result.

    Returns:
        A sanitized string safe for filenames, e.g.
        ``"example.co.uk"``.
    """
    clean = domain.removeprefix("www.")
    return "".join(c if c.isalnum() or c in ".-" else "_" for c in clean)[:max_length]
