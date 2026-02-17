"""Shared cache management utilities.

Caches live under ``server/.cache/``:

- ``domain/`` — per-site domain knowledge (tracker labels, etc.)
- ``overlay/`` — per-site overlay dismissal strategies
- ``scripts/`` — per-script-domain analysis results (cross-site)

This module provides helpers that operate across all cache
directories.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import shutil
import tempfile

from src.utils import logger

log = logger.create_logger("CacheManager")

# Root cache directory — parent of domain/, overlay/, scripts/.
_CACHE_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent / ".cache"


def atomic_write_text(path: pathlib.Path, content: str) -> None:
    """Write *content* to *path* atomically.

    Writes to a temporary file in the same directory, then
    replaces the target via ``os.replace`` which is atomic on
    POSIX filesystems.  This prevents partial/corrupt files when
    two analyses race on the same domain cache.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent),
        suffix=".tmp",
        prefix=path.stem,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except BaseException:
        # Clean up the temp file on any failure.
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def clear_all() -> int:
    """Delete every file in all cache sub-directories.

    Returns the number of files removed.  The sub-directories
    themselves are recreated (empty) so subsequent writes don't
    need to ``mkdir``.
    """
    if not _CACHE_ROOT.exists():
        log.info("No cache directory to clear", {"path": str(_CACHE_ROOT)})
        return 0

    removed = 0
    for child in sorted(_CACHE_ROOT.iterdir()):
        if child.is_dir():
            count = sum(1 for f in child.iterdir() if f.is_file())
            if count:
                shutil.rmtree(child)
                child.mkdir(parents=True, exist_ok=True)
                removed += count
                log.info(
                    "Cache directory cleared",
                    {"directory": child.name, "filesRemoved": count},
                )
        elif child.is_file():
            child.unlink()
            removed += 1

    log.success("All caches cleared", {"totalFilesRemoved": removed})
    return removed
