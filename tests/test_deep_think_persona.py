"""GPT-5.5 Deep Think receives the same selected persona as the voice."""

import asyncio

import pytest

from core import deep_think, persona_briefs as P


def _capture(monkeypatch):
    seen = {}

    async def fake(messages, model):
        seen["system"] = messages[0]["content"]
        return "the answer"
    monkeypatch.setattr(deep_think, "_call_openai", fake)
    return seen


@pytest.mark.parametrize("name", P.SELECTABLE)
def test_deep_think_speaks_as_the_selected_persona(monkeypatch, name):
    seen = _capture(monkeypatch)
    asyncio.run(deep_think.think("plan the thing", persona=name))
    assert seen["system"] == P.deep_think_system_prompt(name)
    assert P.get(name).block in seen["system"]


def test_deep_think_defaults_to_argo_when_no_persona_is_given(monkeypatch):
    seen = _capture(monkeypatch)
    asyncio.run(deep_think.think("plan the thing"))
    assert P.get("argo").block in seen["system"]


def test_deep_think_stays_speakable_and_concise(monkeypatch):
    seen = _capture(monkeypatch)
    asyncio.run(deep_think.think("compare a and b", persona="argo"))
    s = seen["system"].lower()
    assert "read aloud" in s and "no bullets" in s and "well under a minute" in s


def test_the_agent_passes_the_session_persona_to_deep_think():
    """Source-level: think_deeply hands cfg.personality through."""
    import inspect

    import livekit_realtime_agent as agent_mod

    src = inspect.getsource(agent_mod.ArgoRealtimeAgent.think_deeply)
    assert "persona=cfg.personality" in src
