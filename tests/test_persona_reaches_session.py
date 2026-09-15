"""The selected personality reaches the actual Realtime session - proven, not assumed.

The chain is: dashboard -> runtime/voice_personality.json (server-side) ->
get_livekit_realtime_config() on the NEXT session -> the Agent's instructions
-> the fingerprint logged as 'Active now' and written to voice_active.json.
Each link is checked here against the real objects, not mocks of them.
"""

import json

import pytest

from core import livekit_config, persona_briefs as P


@pytest.fixture
def selection(tmp_path, monkeypatch):
    """Point the cross-process handoff files at a temp dir."""
    monkeypatch.setattr(livekit_config, "VOICE_PERSONALITY_FILE", tmp_path / "voice_personality.json")
    monkeypatch.delenv("ARGO_REALTIME_PERSONALITY", raising=False)

    def choose(name):
        livekit_config.write_voice_personality(name)
        return livekit_config.get_livekit_realtime_config()
    return choose


@pytest.mark.parametrize("name", P.SELECTABLE)
def test_persisted_selection_becomes_the_session_instructions(selection, name):
    cfg = selection(name)
    assert cfg.personality == name
    assert cfg.instructions == P.compose_instructions(name)
    assert cfg.instruction_fingerprint == P.instruction_fingerprint(cfg.instructions)


def test_the_agent_object_is_handed_exactly_those_instructions(selection):
    """The Agent constructor used to append its own tool paragraph. It must not."""
    import livekit_realtime_agent as agent_mod

    cfg = selection("jarvis")
    agent = agent_mod.ArgoRealtimeAgent(cfg)
    assert agent.instructions == cfg.instructions
    assert P.get("jarvis").block in agent.instructions
    assert P.get("argo").block not in agent.instructions


def test_switching_changes_the_fingerprint_for_the_next_session(selection):
    first = selection("argo").instruction_fingerprint
    second = selection("rick").instruction_fingerprint
    assert first != second
    assert selection("argo").instruction_fingerprint == first


def test_status_reports_saved_for_next_separately_from_active_now(selection, monkeypatch, tmp_path):
    from core import voice_active

    monkeypatch.setattr(voice_active, "ACTIVE_FILE", tmp_path / "voice_active.json")
    selection("tommy_mix")

    # A session that started as argo is still argo, whatever was saved since.
    import os

    voice_active.write_active(model="gpt-realtime-2.1", voice="marin", personality="argo",
                              instruction_fingerprint=P.instruction_fingerprint(P.compose_instructions("argo")))
    status = livekit_config.livekit_status()
    assert status["saved_for_next"]["personality"] == "tommy_mix"
    assert status["active_now"]["personality"] == "argo"
    assert status["active_now"]["live"] is True
    assert status["active_now"]["pid"] == os.getpid()


def test_an_active_record_from_a_dead_worker_is_not_reported_live(monkeypatch, tmp_path):
    from core import voice_active

    monkeypatch.setattr(voice_active, "ACTIVE_FILE", tmp_path / "voice_active.json")
    voice_active.write_active(model="m", voice="v", personality="argo", instruction_fingerprint="x")
    record = json.loads(voice_active.ACTIVE_FILE.read_text())
    record["pid"] = 999999
    voice_active.ACTIVE_FILE.write_text(json.dumps(record))
    assert voice_active.read_active()["live"] is False


def test_status_lists_personas_with_descriptions_argo_first():
    personas = livekit_config.livekit_status()["personas"]
    assert personas[0]["name"] == "argo"
    assert all(p["description"] for p in personas)
    assert {p["name"] for p in personas} == set(P.SELECTABLE)
