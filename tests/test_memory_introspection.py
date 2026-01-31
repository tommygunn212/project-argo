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


def make_pipeline(tmp_path):
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    pipeline = ArgoPipeline(DummyAudio(), broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._ephemeral_memory = {"temp": "yes"}
    return pipeline, logs


def handle(pipeline, logs, text):
    logs.clear()
    handled = pipeline._handle_memory_command(text, "test", False, {})
    return handled, list(logs)


def test_memory_stats(tmp_path):
    p, logs = make_pipeline(tmp_path)
    p._memory_store.add_memory("FACT", "key", "value", source="user")
    handled, logs_out = handle(p, logs, "memory stats")
    assert handled is True
    assert any("Memory stats" in msg for msg in logs_out)


def test_explain_memory(tmp_path):
    p, logs = make_pipeline(tmp_path)
    p._memory_store.add_memory("FACT", "key", "value", source="user")
    handled, logs_out = handle(p, logs, "explain memory key")
    assert handled is True
    assert any("FACT key = value" in msg for msg in logs_out)
