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
    return pipeline


def test_memory_context_includes_read_only(tmp_path):
    p = make_pipeline(tmp_path)
    p._memory_store.add_memory("FACT", "user.name", "Alex", source="user")
    p._memory_store.add_memory("PROJECT", "repo", "argo", source="user", namespace=p._get_project_namespace())
    ctx = p._get_memory_context("test")
    assert "FACT" in ctx
    assert "PROJECT" in ctx
    assert "EPHEMERAL" in ctx
