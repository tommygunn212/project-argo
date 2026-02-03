import pytest
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
