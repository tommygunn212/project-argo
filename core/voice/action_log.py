"""Every action ARGO takes, written down: what she called, with what, and what came back.

Tommy chose no confirmation gates for the beta and full logging instead, so
when something odd happens the answer to "what did she actually do?" is one
file, not a guess. One JSON line per tool call at
``runtime/logs/actions.jsonl``, covering every tool the realtime model can
reach - ARGO's own capability tools and any MCP server tools alike - because
it listens to the session's ``function_tools_executed`` event rather than
wrapping tools one at a time.

Two rules, the same as the rest of the diagnostics:

  * It never raises into the session. Logging must not be what breaks voice.
  * Secrets never land in the file. Values under secret-shaped keys are
    blanked and key/token-shaped strings are masked wherever they appear
    (AGENTS.md invariant 5).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core import voice_events

logger = logging.getLogger("ARGO.Actions")

ROOT = Path(__file__).resolve().parents[2]
ACTION_LOG = ROOT / "runtime" / "logs" / "actions.jsonl"

MAX_FIELD_CHARS = 2000
_SECRET_KEYS = re.compile(r"pass(word)?|secret|token|api[_-]?key|auth|credential|cookie",
                          re.IGNORECASE)
_SECRET_VALUES = (
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), "***jwt***"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer ***"),
)
_lock = threading.Lock()


def enabled() -> bool:
    """The action log is on unless ARGO_ACTION_LOG is set to 0/false/off."""
    return os.getenv("ARGO_ACTION_LOG", "1").strip().lower() not in {"0", "false", "off", "no"}


def mask_text(text: str) -> str:
    """Key- and token-shaped substrings masked, then clipped to a readable size."""
    for pattern, replacement in _SECRET_VALUES:
        text = pattern.sub(replacement, text)
    if len(text) > MAX_FIELD_CHARS:
        text = text[:MAX_FIELD_CHARS] + f"... [{len(text) - MAX_FIELD_CHARS} more chars]"
    return text


def redact(value: Any) -> Any:
    """A copy of a tool's arguments or result that is safe to write to disk."""
    if isinstance(value, dict):
        return {k: ("***" if _SECRET_KEYS.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return mask_text(value)
    return value


def _parse_json(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def _looks_failed(output: Any, is_error: bool) -> bool:
    if is_error:
        return True
    return isinstance(output, dict) and output.get("ok") is False


def record(tool: str, arguments: Any, output: Any, *, is_error: bool = False,
           call_id: str = "", room: str = "") -> dict | None:
    """Append one action to the log and the event stream. Never raises."""
    if not enabled():
        return None
    try:
        args = redact(_parse_json(arguments))
        out = redact(_parse_json(output))
        entry = {
            "t": time.time(),
            "clock": datetime.now().isoformat(timespec="milliseconds"),
            "room": room,
            "tool": tool,
            "call_id": call_id,
            "arguments": args,
            "ok": not _looks_failed(out, is_error),
            "output": out,
        }
        line = json.dumps(entry, default=str)
        with _lock:
            ACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
            with ACTION_LOG.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        logger.info("[Action] %s ok=%s", tool, entry["ok"])
        voice_events.emit("action", tool=tool, ok=entry["ok"], call_id=call_id)
        return entry
    except Exception:
        logger.debug("[Action] could not record %s", tool, exc_info=True)
        return None


def wire_action_log(session, *, room: str = "") -> None:
    """Write every tool call the session executes to the action log."""
    def on_tools_executed(event) -> None:
        try:
            calls = list(getattr(event, "function_calls", []) or [])
            outputs = list(getattr(event, "function_call_outputs", []) or [])
            for index, call in enumerate(calls):
                output = outputs[index] if index < len(outputs) else None
                record(
                    str(getattr(call, "name", "?")),
                    getattr(call, "arguments", ""),
                    getattr(output, "output", None) if output is not None else None,
                    is_error=bool(getattr(output, "is_error", False)) if output is not None else False,
                    call_id=str(getattr(call, "call_id", "") or ""),
                    room=room,
                )
        except Exception:
            logger.debug("[Action] tools-executed handler failed", exc_info=True)

    try:
        session.on("function_tools_executed", on_tools_executed)
    except Exception:
        logger.debug("[Action] could not subscribe to function_tools_executed", exc_info=True)


def recent(limit: int = 20) -> list[dict]:
    """The last few actions, newest last - for the dashboard or a voice question."""
    try:
        lines = ACTION_LOG.read_text(encoding="utf-8").splitlines()[-limit:]
    except FileNotFoundError:
        return []
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries
