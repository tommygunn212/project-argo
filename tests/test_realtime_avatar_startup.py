"""Retired avatar services must never delay or replace working voice output."""

import asyncio
from types import SimpleNamespace

def test_retired_hedra_never_constructs_plugin_or_replaces_audio(monkeypatch):
    # Isolate the agent module's startup environment defaults from other tests.
    monkeypatch.setenv("LIVEKIT_URL", "ws://127.0.0.1:1")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret")
    import livekit_realtime_agent as agent

    monkeypatch.setenv("ARGO_HEDRA_AVATAR_ENABLED", "true")
    monkeypatch.setenv("HEDRA_API_KEY", "test-only")

    def forbidden_avatar(**kwargs):
        raise AssertionError("Retired Hedra service must not be contacted")

    monkeypatch.setattr(agent, "hedra_plugin", SimpleNamespace(AvatarSession=forbidden_avatar))
    original_audio = object()
    session = SimpleNamespace(output=SimpleNamespace(audio=original_audio))

    result = asyncio.run(agent._maybe_start_hedra_avatar(session, object()))

    assert result is None
    assert session.output.audio is original_audio
