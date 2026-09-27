"""Avatars must never delay or replace working voice output.

Avatar video is optional; ARGO's voice is not. These pin the degrade-forward
rule in core/voice/avatars.py without any network or LiveKit room.
"""

import asyncio
from types import SimpleNamespace

import pytest

from core.voice import avatars


def _session():
    direct_audio = object()
    return SimpleNamespace(output=SimpleNamespace(audio=direct_audio)), direct_audio


def test_retired_hedra_is_never_contacted(monkeypatch):
    monkeypatch.setenv("ARGO_HEDRA_AVATAR_ENABLED", "true")
    monkeypatch.setenv("HEDRA_API_KEY", "test-only")
    monkeypatch.delenv("ARGO_SIMLI_AVATAR_ENABLED", raising=False)
    session, direct_audio = _session()

    assert asyncio.run(avatars.start_avatar(session, object())) is None
    assert session.output.audio is direct_audio
    assert not hasattr(avatars, "hedra_plugin")


@pytest.mark.parametrize("url,reachable", [
    ("ws://127.0.0.1:7880", False),
    ("ws://localhost:7880", False),
    ("ws://192.168.1.20:7880", False),
    ("wss://argo.example.com", True),
    ("wss://8.8.8.8", True),
    ("", False),
])
def test_cloud_reachability(monkeypatch, url, reachable):
    monkeypatch.delenv("ARGO_AVATAR_ALLOW_LOCAL_URL", raising=False)
    assert avatars.url_reachable_from_cloud(url) is reachable


def test_local_url_override(monkeypatch):
    monkeypatch.setenv("ARGO_AVATAR_ALLOW_LOCAL_URL", "1")
    assert avatars.url_reachable_from_cloud("ws://127.0.0.1:7880")


def test_simli_that_never_joins_gives_the_voice_back(monkeypatch):
    """The 2026-09-20 outage: audio rerouted to an avatar that never arrived."""
    monkeypatch.setenv("ARGO_SIMLI_AVATAR_ENABLED", "1")
    monkeypatch.setenv("SIMLI_API_KEY", "test-only")
    monkeypatch.setenv("SIMLI_FACE_ID", "face")
    monkeypatch.setenv("LIVEKIT_URL", "wss://argo.example.com")
    monkeypatch.setenv("ARGO_AVATAR_START_TIMEOUT", "1")
    closed = []

    class FakeAvatar:
        avatar_identity = "simli-avatar"

        def __init__(self, **kwargs):
            pass

        async def start(self, session, room):
            session.output.audio = object()  # what the real plugin does

        async def aclose(self):
            closed.append(True)

    async def never_joins(room, identity):
        await asyncio.sleep(60)

    monkeypatch.setattr(avatars, "simli_plugin",
                        SimpleNamespace(AvatarSession=FakeAvatar, SimliConfig=lambda **k: k))
    from livekit.agents import utils as lk_utils
    monkeypatch.setattr(lk_utils, "wait_for_participant", never_joins)
    session, direct_audio = _session()

    assert asyncio.run(avatars.start_avatar(session, object())) is None
    assert session.output.audio is direct_audio
    assert closed == [True]
