"""Regression tests for personality wiring into LiveKit realtime sessions.

Covers the cross-process handoff: the UI writes a selection, and the next
realtime session composes it into the model instructions. The realtime worker
is a separate process, so none of this can rely on core.config's in-memory
runtime overrides.
"""

import json

import pytest

import personas
from core import livekit_config


SELECTABLE = ["tommy_gunn", "jarvis", "tommy_mix", "rick", "claptrap", "plain"]


# --- registry -------------------------------------------------------------

def test_importing_personas_populates_registry():
    """Must not depend on core.pipeline being imported first."""
    for name in SELECTABLE + ["neutral"]:
        assert name in personas.PERSONA_REGISTRY


def test_every_selectable_persona_has_a_voice_style():
    for name in SELECTABLE:
        style = personas.get_voice_style(name)
        assert style, f"{name} has no VOICE_STYLE"
        assert len(style) > 40, f"{name} VOICE_STYLE is too thin to steer the model"


def test_unknown_persona_returns_empty_style():
    assert personas.get_voice_style("does_not_exist") == ""


# --- instruction composition ---------------------------------------------

def test_compose_includes_style_and_guardrails():
    out = livekit_config.compose_realtime_instructions("BASE.", "jarvis")
    assert out.startswith("BASE.")
    assert personas.get_voice_style("jarvis") in out
    # Personality must be manner only, never scripted lines.
    assert "catchphrase" in out.lower()
    assert "the answer wins" in out.lower()


def test_compose_with_unknown_persona_returns_base_unchanged():
    assert livekit_config.compose_realtime_instructions("BASE.", "nope") == "BASE."


def test_each_persona_produces_distinct_instructions():
    seen = {livekit_config.compose_realtime_instructions("BASE.", n) for n in SELECTABLE}
    assert len(seen) == len(SELECTABLE)


# --- persistence / cross-process handoff ----------------------------------

@pytest.fixture
def temp_personality_file(tmp_path, monkeypatch):
    path = tmp_path / "voice_personality.json"
    monkeypatch.setattr(livekit_config, "VOICE_PERSONALITY_FILE", path)
    monkeypatch.delenv("ARGO_REALTIME_PERSONALITY", raising=False)
    return path


def test_write_then_read_round_trip(temp_personality_file):
    livekit_config.write_voice_personality("rick")
    assert livekit_config.read_voice_personality() == "rick"
    assert json.loads(temp_personality_file.read_text(encoding="utf-8"))["personality"] == "rick"


def test_selection_changes_without_restart(temp_personality_file):
    """Each read re-resolves, so a new session picks up a mid-run change."""
    livekit_config.write_voice_personality("jarvis")
    first = livekit_config.read_voice_personality()
    livekit_config.write_voice_personality("claptrap")
    assert first == "jarvis"
    assert livekit_config.read_voice_personality() == "claptrap"


def test_missing_file_falls_back_to_config_default(temp_personality_file):
    assert not temp_personality_file.exists()
    assert livekit_config.read_voice_personality()  # never empty, never raises


def test_corrupt_file_falls_back_instead_of_raising(temp_personality_file):
    temp_personality_file.write_text("{ not json", encoding="utf-8")
    assert livekit_config.read_voice_personality()


def test_blank_selection_is_ignored(temp_personality_file):
    livekit_config.write_voice_personality("rick")
    livekit_config.write_voice_personality("   ")
    assert livekit_config.read_voice_personality() == "rick"


def test_env_override_beats_persisted_file(temp_personality_file, monkeypatch):
    livekit_config.write_voice_personality("rick")
    monkeypatch.setenv("ARGO_REALTIME_PERSONALITY", "plain")
    assert livekit_config.read_voice_personality() == "plain"


# --- end to end through the session config --------------------------------

def test_session_config_carries_selected_personality(temp_personality_file):
    livekit_config.write_voice_personality("claptrap")
    cfg = livekit_config.get_livekit_realtime_config()
    assert cfg.personality == "claptrap"
    assert personas.get_voice_style("claptrap") in cfg.instructions
