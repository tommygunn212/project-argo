"""A structured record of what actually happened in a voice session.

The mic harness used to reconstruct this by scraping whichever log looked
freshest and matching "ts - LEVEL - message". That failed twice over: the
realtime worker writes JSON lines, not that format, and it writes them to
whichever file the launcher redirected stdout to - which the harness had no
way to know. Ten minutes of talking produced six empty event files and no
indication anything was wrong.

So the session writes its own events here instead, in one known place, in one
known shape. The harness tails this file and nothing else.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENT_FILE = ROOT / "runtime" / "voice_tests" / "live_events.jsonl"

_lock = threading.Lock()


def emit(kind: str, **fields) -> None:
    """Append one event. Never raises - diagnostics must not break voice."""
    try:
        record = {
            "t": time.time(),
            "clock": datetime.now().isoformat(timespec="milliseconds"),
            "pid": os.getpid(),
            "kind": kind,
        }
        record.update(fields)
        line = json.dumps(record, default=str)
        with _lock:
            EVENT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with EVENT_FILE.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:
        pass


def tail_position() -> int:
    """Byte offset to read from, so a scenario only sees its own events."""
    try:
        return EVENT_FILE.stat().st_size
    except Exception:
        return 0


def read_since(offset: int) -> list[dict]:
    """Every event appended after `offset`."""
    try:
        with EVENT_FILE.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            raw = handle.read()
    except Exception:
        return []

    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events
