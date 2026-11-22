"""core/voice/voice_output.py: a designed ElevenLabs voice, never at the cost of the voice."""

from core.voice import voice_output as V


def _settings(**voice):
    return V.load_settings({"voice_output": {"provider": "elevenlabs",
                                             "elevenlabs": {"voice_id": "abc123", **voice}}})


def test_openai_is_the_default(monkeypatch):
    monkeypatch.delenv("ARGO_VOICE_PROVIDER", raising=False)
    assert V.load_settings({}).provider == "openai"
    assert V.build_tts(V.load_settings({})) is None


def test_missing_key_falls_back_to_the_realtime_voice(monkeypatch):
    events = []
    monkeypatch.setattr(V.voice_events, "emit", lambda kind, **f: events.append((kind, f)))
    monkeypatch.delenv("ELEVEN_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert V.build_tts(_settings()) is None
    assert events and events[0][0] == "voice_output_fallback"
    assert "ELEVEN_API_KEY" in events[0][1]["reason"]


def test_missing_voice_id_falls_back(monkeypatch):
    monkeypatch.setattr(V.voice_events, "emit", lambda *a, **k: None)
    monkeypatch.setenv("ELEVEN_API_KEY", "test-key-not-real")
    monkeypatch.delenv("ARGO_ELEVENLABS_VOICE_ID", raising=False)
    assert V.build_tts(_settings(voice_id="")) is None


def test_key_and_voice_give_elevenlabs_with_an_openai_backup(monkeypatch):
    monkeypatch.setattr(V.voice_events, "emit", lambda *a, **k: None)
    monkeypatch.setenv("ELEVEN_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    from livekit.agents import tts as agents_tts
    from livekit.plugins import elevenlabs, openai

    built = V.build_tts(_settings(model="eleven_flash_v2_5", stability=0.3))
    assert isinstance(built, agents_tts.FallbackAdapter)
    kinds = [type(t) for t in built._tts_instances]
    assert kinds[0] is elevenlabs.TTS and kinds[1] is openai.TTS


def test_the_alternate_key_name_works(monkeypatch):
    monkeypatch.setattr(V.voice_events, "emit", lambda *a, **k: None)
    monkeypatch.delenv("ELEVEN_API_KEY", raising=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-not-real")
    assert V.elevenlabs_key() == "test-key-not-real"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("ARGO_VOICE_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ARGO_ELEVENLABS_VOICE_ID", "from-env")
    s = V.load_settings({})
    assert s.provider == "elevenlabs" and s.elevenlabs.voice_id == "from-env"


def test_text_only_model_when_a_tts_speaks(monkeypatch):
    from core.livekit_config import get_livekit_realtime_config
    from core.voice import model as M

    captured = {}

    class FakeRealtime:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setattr(M.openai.realtime, "RealtimeModel", FakeRealtime)
    M.build_realtime_model(get_livekit_realtime_config(), text_only=True)
    assert captured["modalities"] == ["text"]
    M.build_realtime_model(get_livekit_realtime_config())
    assert captured["modalities"] == ["text", "audio"]
