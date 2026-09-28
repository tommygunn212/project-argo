import json
import uuid

from wrapper.session_ids import resolve_session_id


def test_named_session_is_persisted_and_reused(tmp_path):
    session_file = tmp_path / "logs" / ".sessions.json"

    first = resolve_session_id("work", session_file)
    second = resolve_session_id("work", session_file)

    assert first == second
    assert uuid.UUID(first)
    assert json.loads(session_file.read_text(encoding="utf-8")) == {"work": first}


def test_new_name_preserves_existing_sessions(tmp_path):
    session_file = tmp_path / ".sessions.json"
    session_file.write_text('{"existing": "fixed-id"}', encoding="utf-8")

    created = resolve_session_id("new", session_file)

    assert json.loads(session_file.read_text(encoding="utf-8")) == {
        "existing": "fixed-id",
        "new": created,
    }
