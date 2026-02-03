from pathlib import Path
import sqlite3
import tempfile

from core.pipeline import ArgoPipeline
from core.memory_store import MemoryStore


class DummyAudio:
    def acquire_audio(self, *args, **kwargs):
        return True
    def release_audio(self, *args, **kwargs):
        return True
    def stop_playback(self, *args, **kwargs):
        return True
    def force_release_audio(self, *args, **kwargs):
        return True


def make_pipeline(db_path: Path):
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    pipeline = ArgoPipeline(DummyAudio(), broadcast)
    pipeline._memory_store = MemoryStore(db_path)
    pipeline._ephemeral_memory = {}
    pipeline._last_stt_metrics = {"confidence": 0.99}
    return pipeline, logs


def handle(pipeline, logs, text):
    logs.clear()
    handled = pipeline._handle_memory_command(text, "test", False, {})
    return handled, list(logs)


def test_phase1_intent_explicit_vs_implicit(tmp_path):
    db = tmp_path / "memory.db"
    p, logs = make_pipeline(db)

    handled, _ = handle(p, logs, "I like jazz music.")
    assert handled is False
    assert p._memory_store.list_memory() == []

    handled, logs_out = handle(p, logs, "Remember that I like jazz music.")
    assert handled is True
    assert any("you want me to remember" in msg.lower() for msg in logs_out)
    handled, _ = handle(p, logs, "yes")
    assert handled is True
    facts = p._memory_store.list_memory("FACT")
    assert len(facts) == 1
    assert facts[0].key == "user.likes"
    assert "jazz" in facts[0].value.lower()

    handled, logs_out = handle(p, logs, "You should probably remember this.")
    assert handled is True
    assert p._memory_store.list_memory("FACT")
    assert any("What should I remember" in msg for msg in logs_out)


def test_phase2_memory_types(tmp_path):
    db = tmp_path / "memory.db"
    p, logs = make_pipeline(db)

    handle(p, logs, "Remember my favorite editor is VS Code.")
    handle(p, logs, "confirm")
    facts = p._memory_store.list_memory("FACT")
    assert any(m.key == "my favorite editor" for m in facts)

    handle(p, logs, "For the ARGO project, remember the music DB is SQLite.")
    handle(p, logs, "confirm")
    projects = p._memory_store.list_memory("PROJECT", namespace="argo")
    assert len(projects) == 1
    assert "sqlite" in projects[0].value.lower()

    handled, logs_out = handle(p, logs, "Remember this as a preference: editor is VS Code.")
    assert handled is True
    assert any("you want me to remember" in msg.lower() for msg in logs_out)
    handled, logs_out = handle(p, logs, "confirm")
    assert handled is True
    assert any("memory stored" in msg.lower() for msg in logs_out)


def test_phase3_negative_and_adversarial(tmp_path):
    db = tmp_path / "memory.db"
    p, logs = make_pipeline(db)

    handled, logs_out = handle(p, logs, "Remember EVERYTHING I say from now on.")
    assert handled is True
    assert p._memory_store.list_memory() == []
    assert any("can't store everything" in msg.lower() for msg in logs_out)

    handled, logs_out = handle(p, logs, "Remember remember remember.")
    assert handled is True
    assert any("What should I remember" in msg for msg in logs_out)

    handle(p, logs, "Remember my favorite editor is VS Code.")
    handle(p, logs, "confirm")
    handled, logs_out = handle(p, logs, "Remember my favorite editor is Emacs.")
    assert handled is True
    assert any("you want me to remember" in msg.lower() for msg in logs_out)


def test_phase4_deletion_and_erase(tmp_path):
    db = tmp_path / "memory.db"
    p, logs = make_pipeline(db)

    handle(p, logs, "Remember my favorite editor is VS Code.")
    handle(p, logs, "confirm")
    handled, logs_out = handle(p, logs, "List memory.")
    assert handled is True
    assert any("Memory:" in msg for msg in logs_out)

    handled, logs_out = handle(p, logs, "Forget my favorite editor.")
    assert handled is True
    assert any("Deleted memory" in msg for msg in logs_out)

    handle(p, logs, "For the ARGO project, remember the music DB is SQLite.")
    handle(p, logs, "confirm")
    handled, logs_out = handle(p, logs, "Clear memory for ARGO project.")
    assert handled is True
    assert any("Cleared project memory" in msg for msg in logs_out)

    handle(p, logs, "Remember my favorite editor is VS Code.")
    handle(p, logs, "confirm")
    handled, logs_out = handle(p, logs, "Clear all memory.")
    assert handled is True
    assert any("Confirm" in msg for msg in logs_out)

    handled, logs_out = handle(p, logs, "Confirm clear all memory.")
    assert handled is True
    assert any("Cleared all memory" in msg for msg in logs_out)


def test_phase5_failure_resilience(tmp_path):
    db = tmp_path / "memory.db"
    p, logs = make_pipeline(db)

    # Missing directory
    handle(p, logs, "Remember my favorite editor is VS Code.")
    handle(p, logs, "confirm")
    assert p._memory_store.list_memory("FACT")

    # DB lock
    conn = sqlite3.connect(db, timeout=0.0)
    conn.execute("PRAGMA locking_mode=EXCLUSIVE")
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO memory(type, namespace, key, value, source, timestamp) VALUES(?, ?, ?, ?, ?, ?)",
        ("FACT", None, "lock", "lock", "system", "2026-01-31T00:00:00Z"),
    )
    handle(p, logs, "Remember my favorite editor is VS Code.")
    handled, logs_out = handle(p, logs, "confirm")
    conn.rollback()
    conn.close()
    assert handled is True
    assert any("unavailable" in msg.lower() for msg in logs_out)

    # Restart persistence
    p2, logs2 = make_pipeline(db)
    handled, logs_out = handle(p2, logs2, "List memory.")
    assert handled is True
    assert any("Memory:" in msg for msg in logs_out)


def test_phase6_action_isolation(tmp_path):
    db = tmp_path / "memory.db"
    p, logs = make_pipeline(db)

    handled, logs_out = handle(p, logs, "Remember that lights are on.")
    assert handled is True
    assert any("what should i remember" in msg.lower() for msg in logs_out)
