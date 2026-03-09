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

    # Implicit statement (no trigger word) → NOT handled by memory command
    handled, _ = handle(p, logs, "I like jazz music.")
    assert handled is False

    # Explicit "remember" → brain stores directly with confirmation
    handled, logs_out = handle(p, logs, "Remember that I like jazz music.")
    assert handled is True
    # Brain path stores directly: "Got it. I'll remember that."
    assert any("remember" in msg.lower() for msg in logs_out)


def test_phase2_memory_types(tmp_path):
    db = tmp_path / "memory.db"
    p, logs = make_pipeline(db)

    # Brain stores directly without confirmation step
    handled, logs_out = handle(p, logs, "Remember my favorite editor is VS Code.")
    assert handled is True
    assert any("remember" in msg.lower() for msg in logs_out)

    # Project-scoped memory
    handled, logs_out = handle(p, logs, "For the ARGO project, remember the music DB is SQLite.")
    assert handled is True

    # Preference type
    handled, logs_out = handle(p, logs, "Remember this as a preference: editor is VS Code.")
    assert handled is True


def test_phase3_negative_and_adversarial(tmp_path):
    db = tmp_path / "memory.db"
    p, logs = make_pipeline(db)

    # Brain handles bulk requests (may store or reject)
    handled, logs_out = handle(p, logs, "Remember EVERYTHING I say from now on.")
    assert handled is True

    # Redundant trigger words
    handled, logs_out = handle(p, logs, "Remember remember remember.")
    assert handled is True

    # Duplicate/overwrite
    handle(p, logs, "Remember my favorite editor is VS Code.")
    handled, logs_out = handle(p, logs, "Remember my favorite editor is Emacs.")
    assert handled is True


def test_phase4_deletion_and_erase(tmp_path):
    db = tmp_path / "memory.db"
    p, logs = make_pipeline(db)

    # Store something first
    handle(p, logs, "Remember my favorite editor is VS Code.")

    # List memory
    handled, logs_out = handle(p, logs, "List memory.")
    assert handled is True
    assert any("Memory:" in msg for msg in logs_out)

    # Forget specific key
    handled, logs_out = handle(p, logs, "Forget my favorite editor.")
    assert handled is True

    # Clear project memory
    handle(p, logs, "For the ARGO project, remember the music DB is SQLite.")
    handled, logs_out = handle(p, logs, "Clear memory for ARGO project.")
    assert handled is True
    assert any("Cleared project memory" in msg for msg in logs_out)

    # Clear all memory (confirmation flow still works)
    handle(p, logs, "Remember my favorite editor is VS Code.")
    handled, logs_out = handle(p, logs, "Clear all memory.")
    assert handled is True
    assert any("Confirm" in msg for msg in logs_out)

    handled, logs_out = handle(p, logs, "Confirm clear all memory.")
    assert handled is True
    assert any("Cleared all memory" in msg for msg in logs_out)


def test_phase5_failure_resilience(tmp_path):
    db = tmp_path / "memory.db"
    p, logs = make_pipeline(db)

    # Normal store
    handle(p, logs, "Remember my favorite editor is VS Code.")

    # Restart persistence — new pipeline should see stored data
    p2, logs2 = make_pipeline(db)
    handled, logs_out = handle(p2, logs2, "List memory.")
    assert handled is True
    assert any("Memory:" in msg for msg in logs_out)


def test_phase6_action_isolation(tmp_path):
    db = tmp_path / "memory.db"
    p, logs = make_pipeline(db)

    # Memory store command should be handled
    handled, logs_out = handle(p, logs, "Remember that lights are on.")
    assert handled is True
