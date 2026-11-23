"""One running transcript of what Tommy and Argo said, spoken or typed.

The live voice session writes every finished turn here (see
``core/voice/activity.py``), so a typed message sent into that session and a
spoken one land in the same list. The dashboard chat and the board read it to
show "what I said, what she said back". One JSON line per turn at
``runtime/transcript.jsonl``.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

from core.voice.action_log import mask_text

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "runtime" / "transcript.jsonl"
MAX_TEXT = 2000
KEEP_LINES = 1000
_ROLES = {"user": "you", "assistant": "argo"}
_lock = threading.Lock()


def append(role: str, text: str, via: str = "voice") -> dict | None:
    """Record one finished turn. Anything that is not Tommy or Argo is ignored."""
    who = _ROLES.get(str(role).lower())
    text = " ".join(str(text or "").split())
    if not who or not text:
        return None
    entry = {"t": round(time.time(), 3), "clock": datetime.now().isoformat(timespec="seconds"),
             "who": who, "text": mask_text(text)[:MAX_TEXT], "via": via}
    try:
        with _lock:
            FILE.parent.mkdir(parents=True, exist_ok=True)
            with FILE.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
            _trim()
    except OSError:
        return None
    return entry


def _trim() -> None:
    """Keep the file from growing forever: the newest KEEP_LINES turns stay."""
    try:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > KEEP_LINES * 1.5:
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text("\n".join(lines[-KEEP_LINES:]) + "\n", encoding="utf-8")
        tmp.replace(FILE)


def recent(limit: int = 40, since: float = 0.0) -> list[dict]:
    """The newest turns, oldest first. `since` keeps only turns after that time."""
    limit = max(1, min(200, int(limit)))
    try:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines[-(limit * 4 if since else limit):]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("t", 0) > since:
            rows.append(row)
    return rows[-limit:]
