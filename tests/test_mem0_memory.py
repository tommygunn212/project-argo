from core.config import Config
from core.mem0_memory import Mem0Memory, Mem0MemoryConfig, get_mem0_config
from core.memory_store import MemoryStore
from core.pipeline import ArgoPipeline


class FakeMem0Client:
    def __init__(self):
        self.add_calls = []
        self.search_calls = []
        self.deleted_ids = []
        self.cleared_users = []
        self.results = []

    def add(self, messages, **kwargs):
        self.add_calls.append({"messages": messages, "kwargs": kwargs})
        return {"results": [{"id": "new-memory"}]}

    def search(self, query, **kwargs):
        self.search_calls.append({"query": query, "kwargs": kwargs})
        return {"results": self.results}

    def delete(self, memory_id):
        self.deleted_ids.append(memory_id)
        return {"message": "ok"}

    def delete_all(self, **kwargs):
        self.cleared_users.append(kwargs.get("user_id"))
        return {"message": "ok"}


class DummyAudio:
    def acquire_audio(self, *args, **kwargs):
        return True

    def release_audio(self, *args, **kwargs):
        return True

    def stop_playback(self, *args, **kwargs):
        return True

    def force_release_audio(self, *args, **kwargs):
        return True


class FakeMem0Adapter:
    enabled = True

    def format_context(self, query):
        return "MEM0 LONG-TERM MEMORY:\n- Tommy likes fast back-and-forth voice chat."


def make_mem0(fake):
    return Mem0Memory(
        Mem0MemoryConfig(enabled=True, api_key="test-key", user_id="tommy"),
        client_factory=lambda api_key: fake,
    )


def test_mem0_config_disabled_without_key(monkeypatch):
    monkeypatch.delenv("MEM0_API_KEY", raising=False)
    monkeypatch.delenv("ARGO_MEM0_ENABLED", raising=False)

    cfg = get_mem0_config(config=Config({"memory": {"mem0": {}}}))

    assert cfg.enabled is False


def test_mem0_config_string_false_disables(monkeypatch):
    monkeypatch.delenv("MEM0_API_KEY", raising=False)

    cfg = get_mem0_config(
        config=Config({"memory": {"mem0": {"enabled": "false", "api_key": "test-key"}}})
    )

    assert cfg.enabled is False


def test_mem0_remember_fact_uses_user_scope():
    fake = FakeMem0Client()
    mem0 = make_mem0(fake)

    assert mem0.remember_fact("preference", "conversation speed", "is", "fast", source="test")

    call = fake.add_calls[0]
    assert call["kwargs"]["user_id"] == "tommy"
    assert call["kwargs"]["metadata"]["kind"] == "fact"
    assert call["kwargs"]["metadata"]["category"] == "preference"
    assert "conversation speed is fast" in call["messages"][0]["content"]


def test_mem0_format_context_searches_with_user_filter_and_dedupes():
    fake = FakeMem0Client()
    fake.results = [
        {"id": "m1", "memory": "Tommy prefers quick voice replies."},
        {"id": "m2", "memory": "Tommy prefers quick voice replies."},
        {"id": "m3", "memory": "ARGO should keep banter light."},
    ]
    mem0 = make_mem0(fake)

    context = mem0.format_context("voice reply speed")

    assert fake.search_calls[0]["kwargs"]["filters"] == {"user_id": "tommy"}
    assert fake.search_calls[0]["kwargs"]["top_k"] == 5
    assert context.startswith("MEM0 LONG-TERM MEMORY:")
    assert context.count("Tommy prefers quick voice replies.") == 1
    assert "ARGO should keep banter light." in context


def test_mem0_delete_matching_and_clear_user():
    fake = FakeMem0Client()
    fake.results = [
        {"id": "m1", "memory": "delete me"},
        {"memory_id": "m2", "memory": "delete me too"},
    ]
    mem0 = make_mem0(fake)

    assert mem0.delete_matching("delete me") == 2
    assert fake.deleted_ids == ["m1", "m2"]

    assert mem0.clear_user()
    assert fake.cleared_users == ["tommy"]


def test_pipeline_memory_context_includes_mem0(tmp_path):
    pipeline = ArgoPipeline(DummyAudio(), lambda kind, payload: None)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    pipeline._mem0_memory = FakeMem0Adapter()

    context = pipeline._get_memory_context("test", user_text="how should voice chat feel")

    assert "MEM0 LONG-TERM MEMORY" in context
    assert "fast back-and-forth" in context


def test_parse_memory_write_detects_implicit_preference():
    pipeline = ArgoPipeline(DummyAudio(), lambda kind, payload: None)

    write = pipeline._parse_memory_write("I prefer quick back and forth replies.")

    assert write is not None
    assert write["type"] == "PREFERENCE"
    assert write["key"] == "user.preference"
    assert write["value"] == "quick back and forth replies"
    assert write["implicit"] is True
