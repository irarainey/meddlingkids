"""Shared cache management utilities.

All per-domain caches (domain knowledge, overlay strategies,
script analysis) live under ``server/.cache/``.  This module
provides helpers that operate across all cache directories.
"""

from __future__ import annotations

import pathlib
import shutil

from src.utils import logger

log = logger.create_logger("CacheManager")

# Root cache directory — parent of domain/, overlay/, scripts/.
_CACHE_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent / ".cache"


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
