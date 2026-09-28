"""Persistent names for wrapper conversation session identifiers."""

from __future__ import annotations

import json
import uuid
from pathlib import Path


def resolve_session_id(name: str, session_file: str | Path) -> str:
    path = Path(session_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        sessions = json.loads(path.read_text(encoding="utf-8"))
    else:
        sessions = {}
    if name not in sessions:
        sessions[name] = str(uuid.uuid4())
        path.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
    return sessions[name]
