"""Search 19 TB across six drives and come back with something useful.

The old search could not answer "where is my VZBOT build". Two reasons, both
fatal on a machine this size:

  - it matched FILE names only, and most of what Tommy looks for is a
    FOLDER - "my vzbot build", "the davinci assets", "my music"
  - it walked its roots one after another on a 15 second budget, so C:\\
    consumed the whole allowance and the other five drives were never
    touched at all

This walks every root at once, breadth first, so shallow results - which is
where the things people name actually live - come back first and every drive
gets looked at within the budget. Depth is the enemy on a disk with 13,000
music files in it; breadth is the friend.
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger("ARGO.Search")

# Directories that are large, uninteresting, and usually unreadable anyway.
SKIP_DIR_NAMES = {
    "$recycle.bin", "system volume information", "windows", "winsxs",
    "program files", "program files (x86)", "programdata", "msocache",
    "recovery", "perflogs", "node_modules", "__pycache__", ".git", ".venv",
    "venv", "appdata", "temp", "tmp", "cache", "caches",
}


def _skip(name: str) -> bool:
    lowered = name.lower()
    return lowered in SKIP_DIR_NAMES or lowered.startswith("$")


def _score(name: str, query: str) -> int:
    """Exact beats prefix beats contains, so the obvious answer sorts first."""
    lowered = name.lower()
    if lowered == query:
        return 3
    if lowered.startswith(query):
        return 2
    return 1


def search(
    query: str,
    roots: Optional[Iterable[Path]] = None,
    *,
    limit: int = 25,
    seconds: float = 20.0,
    want: str = "any",
) -> dict:
    """Find files and folders whose name contains `query`.

    want: "any", "file" or "folder".
    """
    needle = (query or "").strip().lower()
    if not needle:
        return {"ok": False, "error": "no_query", "message": "What should I look for?"}

    if roots is None:
        from core.filesystem_access import read_roots

        roots = read_roots()
    roots = [Path(r) for r in roots]

    # One queue per root, drained round robin, so no single drive can eat the
    # whole time budget while the others are never opened.
    queues = [deque([root]) for root in roots if root.exists()]
    results: list[dict] = []
    seen_dirs = 0
    started = time.time()
    exhausted = False

    while queues and len(results) < limit * 4:
        if time.time() - started > seconds:
            break
        progressed = False
        for queue in queues:
            if not queue:
                continue
            progressed = True
            current = queue.popleft()
            seen_dirs += 1
            try:
                entries = list(os.scandir(current))
            except (PermissionError, OSError):
                continue

            for entry in entries:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                name = entry.name
                if is_dir and _skip(name):
                    continue
                if needle in name.lower():
                    kind = "folder" if is_dir else "file"
                    if want in ("any", kind):
                        try:
                            size = 0 if is_dir else entry.stat().st_size
                        except OSError:
                            size = 0
                        results.append({
                            "name": name,
                            "path": entry.path,
                            "type": kind,
                            "size": size,
                            "depth": len(Path(entry.path).parts),
                            "score": _score(name, needle),
                        })
                if is_dir:
                    queue.append(Path(entry.path))
        if not progressed:
            exhausted = True
            break

    elapsed = time.time() - started
    results.sort(key=lambda r: (-r["score"], r["depth"], r["name"].lower()))
    trimmed = results[:limit]

    return {
        "ok": True,
        "query": query,
        "count": len(trimmed),
        "found_total": len(results),
        "results": trimmed,
        "searched": [str(r) for r in roots],
        "folders_scanned": seen_dirs,
        "seconds": round(elapsed, 1),
        "complete": exhausted,
        "message": (
            f"{len(trimmed)} match{'' if len(trimmed) == 1 else 'es'} for {query!r}"
            + ("" if exhausted else f" after {elapsed:.0f}s - there may be more deeper down")
        ),
    }
