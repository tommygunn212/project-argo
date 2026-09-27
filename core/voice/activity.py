"""Say, in the log and the event stream, what ARGO heard and what she said.

Without this a silent session and a deaf session look identical: one
"starting ARGO realtime session" line and nothing after it. Every handler
swallows its own errors - diagnostics must never be what breaks voice.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from livekit.agents import AgentSession

from core import voice_events

logger = logging.getLogger("ARGO.LiveKit")


def _item_text(item) -> str:
    return getattr(item, "text_content", "") or ""


def _guarded(name: str, handler: Callable) -> Callable:
    def wrapped(event) -> None:
        try:
            handler(event)
        except Exception:
            logger.debug("[Session] %s handler failed", name, exc_info=True)
    return wrapped


def log_session_activity(session: AgentSession, *, room: str = "", memory=None) -> None:
    """Subscribe the session's events to the log, the event stream and memory."""
    voice_events.emit("session_start", room=room)

    def on_user_input(event) -> None:
        transcript = getattr(getattr(event, "transcript", None), "text", None)
        if transcript is None:
            transcript = getattr(event, "transcript", "")
        logger.info("[Session] heard: %r", transcript)
        voice_events.emit("heard", text=transcript, final=bool(getattr(event, "is_final", False)))

    def on_user_state(event) -> None:
        old, new = str(getattr(event, "old_state", "?")), str(getattr(event, "new_state", "?"))
        logger.info("[Session] user %s -> %s", old, new)
        voice_events.emit("user_state", old=old, new=new)
        if new == "speaking":
            # He has moved on; a deep answer still in flight would talk over
            # him with a paragraph about something else.
            from core import deep_think

            killed = deep_think.cancel_all(reason="user_started_speaking")
            if killed:
                voice_events.emit("deep_think_cancelled", count=killed)

    def on_agent_state(event) -> None:
        old, new = str(getattr(event, "old_state", "?")), str(getattr(event, "new_state", "?"))
        logger.info("[Session] agent %s -> %s", old, new)
        voice_events.emit("agent_state", old=old, new=new)

    def on_conversation_item(event) -> None:
        item = getattr(event, "item", None)
        role, text = str(getattr(item, "role", "?")), _item_text(item)
        logger.info("[Session] %s said: %r", role, text[:200])
        voice_events.emit("said", role=role, text=text[:600])
        if memory is not None:
            memory.note(str(getattr(item, "role", "")), text)

    def on_error(event) -> None:
        detail = getattr(event, "error", event)
        logger.error("[Session] error: %s", detail)
        voice_events.emit("error", detail=str(detail)[:400])

    handlers = {
        "user_input_transcribed": on_user_input,
        "user_state_changed": on_user_state,
        "agent_state_changed": on_agent_state,
        "conversation_item_added": on_conversation_item,
        "error": on_error,
    }
    for name, handler in handlers.items():
        try:
            session.on(name, _guarded(name, handler))
        except Exception:
            logger.debug("[Session] could not subscribe to %s", name, exc_info=True)
