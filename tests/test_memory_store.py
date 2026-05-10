import pytest
import core.memory_store as memory_store
from core.memory_store import MemoryStore


def test_add_and_list_fact(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.add_memory("FACT", "user.name", "Alex", source="user")
    items = store.list_memory("FACT")
    assert len(items) == 1
    assert items[0].key == "user.name"
    assert items[0].value == "Alex"
    assert items[0].type == "FACT"


def test_add_project_and_namespace(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.add_memory("PROJECT", "repo", "argo", source="user", namespace="argo")
    items = store.list_memory("PROJECT", namespace="argo")
    assert len(items) == 1
    assert items[0].namespace == "argo"


def test_delete_memory_by_key(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.add_memory("FACT", "foo", "bar", source="user")
    deleted = store.delete_memory("foo")
    assert deleted == 1
    assert store.list_memory("FACT") == []


def test_clear_project(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.add_memory("PROJECT", "a", "1", source="user", namespace="p1")
    store.add_memory("PROJECT", "b", "2", source="user", namespace="p2")
    cleared = store.clear_project("p1")
    assert cleared == 1
    remaining = store.list_memory("PROJECT")
    assert len(remaining) == 1
    assert remaining[0].namespace == "p2"


def test_clear_all(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.add_memory("FACT", "a", "1", source="user")
    store.add_memory("PROJECT", "b", "2", source="user", namespace="p")
    cleared = store.clear_all()
    assert cleared == 2
    assert store.list_memory() == []


def test_invalid_type_raises(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    with pytest.raises(ValueError):
        store.add_memory("EPHEMERAL", "x", "y", source="user")


def test_preference_type_allowed(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.add_memory("PREFERENCE", "editor", "VS Code", source="user")
    prefs = store.list_memory("PREFERENCE")
    assert len(prefs) == 1


def test_conversation_turn_storage_and_search(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    turn_id = store.add_turn(
        "How should we handle memory?",
        "Use a single backend adapter with SQLite fallback.",
        source="test",
        intent="question",
        metadata={"mode": "unit"},
    )
    assert turn_id > 0

    matches = store.search_turns("backend adapter", limit=3)
    assert len(matches) == 1
    assert matches[0].intent == "question"
    assert matches[0].metadata["mode"] == "unit"


def test_get_memory_store_defaults_to_sqlite(tmp_path, monkeypatch):
    monkeypatch.delenv("ARGO_MEMORY_BACKEND", raising=False)
    monkeypatch.setenv("ARGO_MEMORY_SQLITE_PATH", str(tmp_path / "memory.db"))
    memory_store.reset_memory_store_for_tests()

    store = memory_store.get_memory_store()

    assert store.backend_name == "sqlite"
    assert store.db_path == tmp_path / "memory.db"
    memory_store.reset_memory_store_for_tests()


def test_get_memory_store_selects_postgres(monkeypatch):
    created = {}

    class DummyPostgresStore:
        backend_name = "postgres"

        def __init__(self, dsn):
            created["dsn"] = dsn

    monkeypatch.setenv("ARGO_MEMORY_BACKEND", "postgres")
    monkeypatch.setenv("ARGO_POSTGRES_DSN", "postgresql://argo:argo@localhost:5432/argo")
    monkeypatch.setattr(memory_store, "PostgresMemoryStore", DummyPostgresStore)
    memory_store.reset_memory_store_for_tests()

    store = memory_store.get_memory_store()

    assert store.backend_name == "postgres"
    assert created["dsn"] == "postgresql://argo:argo@localhost:5432/argo"
    memory_store.reset_memory_store_for_tests()
