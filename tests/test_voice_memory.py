"""Tests for Smooth Voice durable memory.

The behaviours that matter: a turn is only stored once both halves arrive, the
same turn is never stored twice, a broken store degrades to a working voice
session, and injected facts stay small and de-duplicated.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import voice_memory as vm  # noqa: E402


class FakeRow:
    def __init__(self, key, value, source="explicit_user_request"):
        self.key = key
        self.value = value
        self.source = source
        self.timestamp = "2026-02-01T00:00:00Z"


class FakeTurn:
    def __init__(self, user_text, assistant_text):
        self.user_text = user_text
        self.assistant_text = assistant_text


class FakeStore:
    backend_name = "fake"

    def __init__(self, facts=None, turns=None, explode=False):
        self.turns_added = []
        self._facts = facts or []
        self._turns = turns or []
        self._explode = explode

    def add_turn(self, user_text, assistant_text, source="assistant", intent=None, metadata=None):
        if self._explode:
            raise RuntimeError("database is on fire")
        self.turns_added.append((user_text, assistant_text, source, metadata))
        return len(self.turns_added)

    def list_memory(self, kind=None, namespace=None):
        if self._explode:
            raise RuntimeError("database is on fire")
        return self._facts if kind == "FACT" else []

    def search_turns(self, query, limit=5):
        if self._explode:
            raise RuntimeError("database is on fire")
        return self._turns[:limit]


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(vm, "_store", lambda: fake)
    monkeypatch.setattr(vm, "_mem0", lambda: None)
    return fake


def _settle():
    """Writes happen on a daemon thread; give them a moment."""
    for _ in range(50):
        time.sleep(0.01)


# --------------------------------------------------------------------------
# Pairing user and assistant items into a turn
# --------------------------------------------------------------------------

def test_a_complete_exchange_is_stored_once(store):
    mem = vm.VoiceMemory(session_id="s1")
    mem.note("user", "what is the bedroom set to")
    mem.note("assistant", "seventy-two")
    _settle()
    assert len(store.turns_added) == 1
    user_text, assistant_text, source, metadata = store.turns_added[0]
    assert user_text == "what is the bedroom set to"
    assert assistant_text == "seventy-two"
    assert source == vm.TURN_SOURCE
    assert metadata == {"session_id": "s1"}


def test_a_user_line_alone_is_not_stored(store):
    mem = vm.VoiceMemory()
    mem.note("user", "hang on")
    _settle()
    assert store.turns_added == []


def test_she_speaks_unprompted_and_nothing_is_stored(store):
    """A greeting with no question before it is not an exchange."""
    mem = vm.VoiceMemory()
    mem.note("assistant", "hey Tommy")
    _settle()
    assert store.turns_added == []


def test_two_user_lines_in_a_row_keep_the_newer_one(store):
    mem = vm.VoiceMemory()
    mem.note("user", "turn on the")
    mem.note("user", "actually turn on the living room")
    mem.note("assistant", "done")
    _settle()
    assert len(store.turns_added) == 1
    assert store.turns_added[0][0] == "actually turn on the living room"


def test_the_same_exchange_arriving_twice_is_stored_once(store):
    mem = vm.VoiceMemory()
    mem.note("user", "what time is it")
    mem.note("assistant", "just past four")
    mem.note("user", "what time is it")
    mem.note("assistant", "just past four")
    _settle()
    assert len(store.turns_added) == 1


def test_a_repeated_question_with_a_new_answer_is_stored_again(store):
    mem = vm.VoiceMemory()
    mem.note("user", "what time is it")
    mem.note("assistant", "just past four")
    mem.note("user", "what time is it")
    mem.note("assistant", "ten past four")
    _settle()
    assert len(store.turns_added) == 2


@pytest.mark.parametrize("fragment", ["", " ", "\n", "a"])
def test_coughs_and_fragments_are_not_turns(store, fragment):
    mem = vm.VoiceMemory()
    mem.note("user", fragment)
    mem.note("assistant", "sorry?")
    _settle()
    assert store.turns_added == []


def test_very_long_speech_is_truncated_not_dropped(store):
    mem = vm.VoiceMemory()
    mem.note("user", "x" * 9000)
    mem.note("assistant", "y" * 9000)
    _settle()
    assert len(store.turns_added) == 1
    assert len(store.turns_added[0][0]) == vm.MAX_TURN_CHARS


def test_flush_discards_a_dangling_half_turn(store):
    mem = vm.VoiceMemory()
    mem.note("user", "are you there")
    mem.flush()
    mem.note("assistant", "yes")
    _settle()
    assert store.turns_added == []


def test_disabled_memory_stores_nothing(store):
    mem = vm.VoiceMemory(enabled=False)
    mem.note("user", "remember this")
    mem.note("assistant", "sure")
    _settle()
    assert store.turns_added == []


# --------------------------------------------------------------------------
# A broken store must never break the voice session
# --------------------------------------------------------------------------

def test_a_failing_store_does_not_raise(monkeypatch):
    monkeypatch.setattr(vm, "_store", lambda: FakeStore(explode=True))
    monkeypatch.setattr(vm, "_mem0", lambda: None)
    mem = vm.VoiceMemory()
    mem.note("user", "hello")
    mem.note("assistant", "hi")
    _settle()
    assert mem.opening_context() == ""
    assert "wrong" in mem.recall("anything").lower()


def test_a_missing_store_does_not_raise(monkeypatch):
    monkeypatch.setattr(vm, "_store", lambda: None)
    monkeypatch.setattr(vm, "_mem0", lambda: None)
    mem = vm.VoiceMemory()
    mem.note("user", "hello")
    mem.note("assistant", "hi")
    _settle()
    assert mem.opening_context() == ""
    assert "can't reach" in mem.recall("anything").lower()


# --------------------------------------------------------------------------
# Facts injected at session start
# --------------------------------------------------------------------------

def test_opening_context_includes_facts(monkeypatch):
    monkeypatch.setattr(vm, "_store", lambda: FakeStore(facts=[FakeRow("name", "Tommy")]))
    monkeypatch.setattr(vm, "_mem0", lambda: None)
    block = vm.VoiceMemory().opening_context()
    assert "name: Tommy" in block
    assert "recite" in block.lower()


def test_opening_context_is_empty_when_there_are_no_facts(monkeypatch):
    monkeypatch.setattr(vm, "_store", lambda: FakeStore(facts=[]))
    monkeypatch.setattr(vm, "_mem0", lambda: None)
    assert vm.VoiceMemory().opening_context() == ""


def test_duplicate_facts_are_said_once(monkeypatch):
    """The live store really does hold 'name = Tommy' twice."""
    facts = [FakeRow("name", "Tommy"), FakeRow("name", "Tommy")]
    monkeypatch.setattr(vm, "_store", lambda: FakeStore(facts=facts))
    monkeypatch.setattr(vm, "_mem0", lambda: None)
    assert vm.VoiceMemory().opening_context().count("name: Tommy") == 1


def test_facts_are_capped_so_instructions_stay_small(monkeypatch):
    facts = [FakeRow(f"key{i}", f"value{i}") for i in range(100)]
    monkeypatch.setattr(vm, "_store", lambda: FakeStore(facts=facts))
    monkeypatch.setattr(vm, "_mem0", lambda: None)
    block = vm.VoiceMemory().opening_context()
    assert block.count("\n- ") <= vm.MAX_FACTS


# --------------------------------------------------------------------------
# Recall
# --------------------------------------------------------------------------

def test_recall_returns_past_exchanges(monkeypatch):
    turns = [FakeTurn("what voice is this", "it is marin")]
    monkeypatch.setattr(vm, "_store", lambda: FakeStore(turns=turns))
    monkeypatch.setattr(vm, "_mem0", lambda: None)
    out = vm.VoiceMemory().recall("voice")
    assert "what voice is this" in out and "it is marin" in out


def test_recall_with_no_hits_says_so(monkeypatch):
    monkeypatch.setattr(vm, "_store", lambda: FakeStore(turns=[]))
    monkeypatch.setattr(vm, "_mem0", lambda: None)
    assert "nothing in my memory" in vm.VoiceMemory().recall("submarines").lower()


def test_recall_needs_a_query(store):
    assert "need something" in vm.VoiceMemory().recall("   ").lower()


def test_recall_limit_is_clamped(monkeypatch):
    turns = [FakeTurn(f"q{i}", f"a{i}") for i in range(50)]
    fake = FakeStore(turns=turns)
    monkeypatch.setattr(vm, "_store", lambda: fake)
    monkeypatch.setattr(vm, "_mem0", lambda: None)
    out = vm.VoiceMemory().recall("q", limit=999)
    assert out.count("He said:") <= 8


# --------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------

def test_stats_report_what_happened(store):
    mem = vm.VoiceMemory(session_id="abc")
    mem.note("user", "one")
    mem.note("assistant", "two")
    _settle()
    stats = mem.stats()
    assert stats["session_id"] == "abc"
    assert stats["turns_written"] == 1
    assert stats["half_turn_pending"] is False


def test_memory_status_is_safe_when_the_store_is_gone(monkeypatch):
    monkeypatch.setattr(vm, "_store", lambda: None)
    monkeypatch.setattr(vm, "_mem0", lambda: None)
    status = vm.memory_status()
    assert status["available"] is False
