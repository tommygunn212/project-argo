"""Prove remembered facts actually reach the live session's instructions.

The personality work already taught us that plumbing which "looks wired" can be
wired to nothing: the worker log said tommy_mix while the model ignored it. So
this asserts against the instructions the Agent was really constructed with,
not against the code that was supposed to build them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

livekit_realtime_agent = pytest.importorskip("livekit_realtime_agent")

from core.livekit_config import get_livekit_realtime_config  # noqa: E402
from core import persona_briefs as pb  # noqa: E402


class FakeMemory:
    def __init__(self, context="", recall_text="recalled"):
        self._context = context
        self._recall_text = recall_text
        self.noted = []

    def opening_context(self):
        return self._context

    def recall(self, about, limit=3):
        return f"{self._recall_text}:{about}"

    def note(self, role, text):
        self.noted.append((role, text))

    def flush(self):
        pass

    def stats(self):
        return {"backend": "fake"}


def _agent(memory=None):
    cfg = get_livekit_realtime_config()
    return livekit_realtime_agent.ArgoRealtimeAgent(cfg, memory=memory), cfg


def _instructions(agent) -> str:
    for attr in ("instructions", "_instructions"):
        value = getattr(agent, attr, None)
        if isinstance(value, str) and value:
            return value
    raise AssertionError("could not read the agent's instructions")


def test_remembered_facts_reach_the_instructions():
    block = "WHAT YOU ALREADY KNOW ABOUT HIM:\n- name: Tommy"
    agent, _ = _agent(FakeMemory(context=block))
    assert "WHAT YOU ALREADY KNOW ABOUT HIM" in _instructions(agent)
    assert "name: Tommy" in _instructions(agent)


def test_the_personality_survives_memory_injection():
    """Facts must be appended to the persona block, never replace it."""
    agent, cfg = _agent(FakeMemory(context="WHAT YOU ALREADY KNOW ABOUT HIM:\n- name: Tommy"))
    text = _instructions(agent)
    assert cfg.instructions in text
    assert text.index(cfg.instructions) < text.index("WHAT YOU ALREADY KNOW")


def test_no_memory_leaves_instructions_untouched():
    agent, cfg = _agent(memory=None)
    assert _instructions(agent) == cfg.instructions


def test_empty_memory_adds_no_dangling_header():
    agent, cfg = _agent(FakeMemory(context=""))
    assert _instructions(agent) == cfg.instructions


def test_a_broken_memory_does_not_stop_the_session():
    class Exploding:
        def opening_context(self):
            raise RuntimeError("store is down")

    agent, cfg = _agent(Exploding())
    assert _instructions(agent) == cfg.instructions


def test_the_recall_tool_exists_and_is_described_for_the_model():
    agent, _ = _agent(FakeMemory())
    assert hasattr(agent, "recall")
    doc = (livekit_realtime_agent.ArgoRealtimeAgent.recall.__doc__ or "").lower()
    assert "remember when" in doc or "past conversations" in doc


def test_memory_injection_does_not_reintroduce_banned_run_ups():
    """A memory block must not undo the concise-first-response contract."""
    block = "WHAT YOU ALREADY KNOW ABOUT HIM:\n- name: Tommy\n- owner: Tommy"
    agent, _ = _agent(FakeMemory(context=block))
    assert pb.find_banned(_instructions(agent)) == []


def test_instructions_stay_within_a_sane_size():
    """Facts are capped precisely so this stays true."""
    block = "WHAT YOU ALREADY KNOW ABOUT HIM:\n" + "\n".join(
        f"- key{i}: value{i}" for i in range(12)
    )
    agent, cfg = _agent(FakeMemory(context=block))
    grew_by = len(_instructions(agent)) - len(cfg.instructions)
    assert grew_by < 1500
