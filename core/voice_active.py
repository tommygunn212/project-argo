"""What the live Smooth Voice session is ACTUALLY running.

The dashboard used to show whatever was saved in config, which is not the
same thing: a personality changed in the dropdown does not reach a session
that is already up. So the worker writes this record the moment a session
starts, from the config it actually used, and marks it ended when the job
shuts down. /api/livekit-status reports it as "active_now" next to what is
saved for the next connection, and the UI shows both - separately.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_FILE = ROOT / "runtime" / "voice_active.json"


def write_active(**fields) -> None:
    """Called by the worker when a session starts. Never raises."""
    try:
        record = {
            "live": True,
            "pid": os.getpid(),
            "started": time.time(),
            "started_human": datetime.now().isoformat(timespec="seconds"),
        }
        record.update(fields)
        ACTIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = ACTIVE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        tmp.replace(ACTIVE_FILE)
    except Exception:
        pass


def mark_ended(reason: str = "") -> None:
    try:
        record = read_active() or {}
        record.update({"live": False, "ended": time.time(),
                       "ended_human": datetime.now().isoformat(timespec="seconds"),
                       "end_reason": reason})
        ACTIVE_FILE.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def read_active() -> dict | None:
    """The record, or None. A record from a pid that no longer exists is
    reported as not live, whatever the file says - a killed worker never
    gets to write its ending."""
    try:
        record = json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    if record.get("live"):
        try:
            import psutil

            if not psutil.pid_exists(int(record.get("pid", -1))):
                record["live"] = False
                record["end_reason"] = "worker process gone"
        except Exception:
            pass
    return record
