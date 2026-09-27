"""core/voice/activity.py: what was heard and said reaches the log, events and memory."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.voice import activity


class FakeSession:
    def __init__(self):
        self.handlers = {}

    def on(self, name, callback):
        self.handlers[name] = callback


def test_session_start_carries_the_room_name():
    """It used to read session._room, which AgentSession does not have, so
    every session_start event reported room=''."""
    with patch("core.voice_events.emit") as emit:
        activity.log_session_activity(FakeSession(), room="argo-room")
    emit.assert_any_call("session_start", room="argo-room")


def test_conversation_items_are_noted_in_memory():
    session, memory = FakeSession(), MagicMock()
    with patch("core.voice_events.emit"):
        activity.log_session_activity(session, memory=memory)
        item = SimpleNamespace(role="user", text_content="remember the blue one")
        session.handlers["conversation_item_added"](SimpleNamespace(item=item))
    memory.note.assert_called_once_with("user", "remember the blue one")


def test_a_failing_handler_never_raises_into_the_session():
    session, memory = FakeSession(), MagicMock()
    memory.note.side_effect = RuntimeError("disk full")
    with patch("core.voice_events.emit"):
        activity.log_session_activity(session, memory=memory)
        item = SimpleNamespace(role="user", text_content="x")
        session.handlers["conversation_item_added"](SimpleNamespace(item=item))
