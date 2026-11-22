"""core/voice/action_log.py: every tool call is written down, secrets never are."""

import json
from types import SimpleNamespace

import pytest

from core.voice import action_log


class FakeSession:
    def __init__(self):
        self.handlers = {}

    def on(self, name, callback):
        self.handlers[name] = callback


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    path = tmp_path / "actions.jsonl"
    monkeypatch.setattr(action_log, "ACTION_LOG", path)
    monkeypatch.setattr(action_log.voice_events, "emit", lambda *a, **k: None)
    monkeypatch.delenv("ARGO_ACTION_LOG", raising=False)
    return path


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _executed(*pairs):
    calls = [SimpleNamespace(name=n, arguments=a, call_id=f"c{i}") for i, (n, a, _o, _e) in enumerate(pairs)]
    outs = [None if o is None else SimpleNamespace(output=o, is_error=e) for (_n, _a, o, e) in pairs]
    return SimpleNamespace(function_calls=calls, function_call_outputs=outs)


def test_every_executed_tool_is_recorded(log_file):
    session = FakeSession()
    action_log.wire_action_log(session, room="living-room")
    session.handlers["function_tools_executed"](_executed(
        ("open_app", '{"name": "orca slicer"}', '{"ok": true}', False),
        ("set_volume", '{"percent": 40}', '{"ok": true}', False),
    ))
    entries = _lines(log_file)
    assert [e["tool"] for e in entries] == ["open_app", "set_volume"]
    assert entries[0]["arguments"] == {"name": "orca slicer"}
    assert entries[0]["room"] == "living-room" and entries[0]["ok"] is True


def test_failures_are_marked_failed(log_file):
    action_log.record("control_ac", {"name": "x"}, '{"ok": false, "error": "offline"}')
    action_log.record("mcp_tool", {}, "boom", is_error=True)
    assert [e["ok"] for e in _lines(log_file)] == [False, False]


def test_secrets_never_reach_the_file(log_file):
    action_log.record(
        "send_thing",
        {"api_key": "plain-value-123", "headers": {"Authorization": "x"},
         "note": "use sk-abcdefghijklmnop please"},
        "token eyJaaaaaaaaaa.bbbbbbbbbb.cccccccccc and Bearer abcdefghijkl",
    )
    raw = log_file.read_text(encoding="utf-8")
    for secret in ("plain-value-123", "sk-abcdefghijklmnop", "eyJaaaaaaaaaa", "abcdefghijkl"):
        assert secret not in raw


def test_negative_control_unredacted_text_does_appear(log_file):
    """Proves the secret test above can fail: ordinary text is written as-is."""
    action_log.record("open_app", {"name": "bambu studio"}, "opened")
    assert "bambu studio" in log_file.read_text(encoding="utf-8")


def test_kill_switch_turns_logging_off(log_file, monkeypatch):
    monkeypatch.setenv("ARGO_ACTION_LOG", "off")
    assert action_log.record("open_app", {}, "x") is None
    assert not log_file.exists()


def test_long_output_is_clipped(log_file):
    action_log.record("read_text_file", {}, "x" * 10000)
    assert len(_lines(log_file)[0]["output"]) < 2100


def test_a_broken_event_never_raises_into_the_session(log_file):
    session = FakeSession()
    action_log.wire_action_log(session)
    session.handlers["function_tools_executed"](object())  # no attributes at all


def test_unwritable_log_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(action_log, "ACTION_LOG", tmp_path / "file_not_dir" / "actions.jsonl")
    (tmp_path / "file_not_dir").write_text("i am a file")
    monkeypatch.setattr(action_log.voice_events, "emit", lambda *a, **k: None)
    assert action_log.record("x", {}, "y") is None


def test_recent_reads_back_newest_last(log_file):
    for name in ("a", "b", "c"):
        action_log.record(name, {}, "ok")
    assert [e["tool"] for e in action_log.recent(2)] == ["b", "c"]
