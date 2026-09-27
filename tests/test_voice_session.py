"""core/voice/session.py: starting a session, and falling back when the model won't run."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.livekit_config import get_livekit_realtime_config
from core.voice import session as voice_session


def _cfg(**overrides):
    return replace(get_livekit_realtime_config(), **overrides)


def test_fallback_starts_a_fresh_session_on_the_fallback_model(monkeypatch):
    """The old fallback assigned session.llm, which is a read-only property on
    AgentSession - so the fallback itself raised and the room went silent."""
    tried = []

    async def start_in_room(ctx, cfg, memory):
        tried.append(cfg.model)
        if cfg.model == "primary":
            raise RuntimeError("model rejected")
        return "session", None

    monkeypatch.setattr(voice_session, "_start_in_room", start_in_room)
    session, avatar, model = asyncio.run(voice_session._start_with_fallback(
        None, _cfg(model="primary", fallback_model="known-good"), None, voice_session.JobIds()))

    assert tried == ["primary", "known-good"]
    assert (session, model) == ("session", "known-good")


def test_no_fallback_means_the_original_error_surfaces(monkeypatch):
    async def start_in_room(ctx, cfg, memory):
        raise RuntimeError("model rejected")

    monkeypatch.setattr(voice_session, "_start_in_room", start_in_room)
    with pytest.raises(RuntimeError):
        asyncio.run(voice_session._start_with_fallback(
            None, _cfg(model="same", fallback_model="same"), None, voice_session.JobIds()))


def test_active_now_reports_the_model_actually_running(monkeypatch):
    written = {}
    monkeypatch.setattr(voice_session.voice_active, "write_active", lambda **f: written.update(f))
    monkeypatch.setattr(voice_session.voice_events, "emit", lambda *a, **k: None)
    voice_session._announce_active(_cfg(model="primary"), "known-good", voice_session.JobIds(room="r"))
    assert written["model"] == "known-good" and written["room"] == "r"


def test_job_ids_tolerate_a_bare_context():
    assert voice_session.JobIds.of(SimpleNamespace()) == voice_session.JobIds()
    ctx = SimpleNamespace(job=SimpleNamespace(id="j1", dispatch_id="d1", room=SimpleNamespace(name="argo")))
    assert voice_session.JobIds.of(ctx) == voice_session.JobIds("j1", "d1", "argo")


def test_errors_are_redacted_before_they_reach_the_event_stream():
    text = voice_session.redacted_error(RuntimeError("bad key sk-abcdefghijklmnop"))
    assert "abcdefghijklmnop" not in text and "sk-***" in text
