"""core/transcript.py: one shared record of what was said, spoken or typed."""

import json

import pytest

from core import transcript as T


@pytest.fixture
def tr(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "FILE", tmp_path / "transcript.jsonl")
    return tmp_path


def test_user_and_assistant_turns_are_kept_in_order(tr):
    T.append("user", "what did I type?")
    T.append("assistant", "You typed hello.")
    rows = T.recent()
    assert [(r["who"], r["text"]) for r in rows] == [("you", "what did I type?"), ("argo", "You typed hello.")]


def test_other_roles_and_empty_text_are_ignored(tr):
    assert T.append("system", "x") is None and T.append("tool", "x") is None
    assert T.append("user", "   \n ") is None and T.append("user", None) is None
    assert T.recent() == []


def test_secrets_are_masked_and_long_text_clipped(tr):
    T.append("user", "my key is sk-abcdefghijklmnop1234")
    T.append("assistant", "x" * 5000)
    rows = T.recent()
    assert "sk-abcdefghijklmnop1234" not in rows[0]["text"] and "sk-***" in rows[0]["text"]
    assert len(rows[1]["text"]) <= T.MAX_TEXT


def test_since_returns_only_newer_turns_and_bad_lines_are_skipped(tr):
    first = T.append("user", "one")
    T.FILE.open("a", encoding="utf-8").write("not json\n")
    second = T.append("assistant", "two")
    assert [r["text"] for r in T.recent(since=first["t"])] == ["two"]
    assert [r["text"] for r in T.recent(since=second["t"])] == []
    assert [r["text"] for r in T.recent()] == ["one", "two"]


def test_the_file_is_trimmed_so_it_cannot_grow_forever(tr, monkeypatch):
    monkeypatch.setattr(T, "KEEP_LINES", 10)
    for i in range(40):
        T.append("user", f"turn {i}")
    lines = T.FILE.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 25 and json.loads(lines[-1])["text"] == "turn 39"


def test_the_live_session_writes_every_conversation_item_to_the_transcript(tr):
    from core.voice import activity

    handlers = {}

    class FakeSession:
        def on(self, name, handler):
            handlers[name] = handler

    activity.log_session_activity(FakeSession(), room="r")
    item = type("Item", (), {"role": "user", "text_content": "typed into the session"})()
    handlers["conversation_item_added"](type("Ev", (), {"item": item})())
    assert T.recent()[0]["text"] == "typed into the session"


def test_board_shows_the_conversation_newest_first(tr, tmp_path, monkeypatch):
    from core import board_service as B

    monkeypatch.setattr(B, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(B, "LAYOUT_FILE", tmp_path / "layouts.json")
    T.append("user", "hello")
    T.append("assistant", "hi Tommy")
    conv = B.snapshot("All", [], [])["conversation"]
    assert [c["who"] for c in conv] == ["argo", "you"] and conv[0]["text"] == "hi Tommy"
