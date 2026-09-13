"""The STT prompt must come from config, never from a hardcoded default.

A biasing prompt is returned verbatim as the transcript when the audio is quiet
or is ARGO's own speech. The pipeline then answers its own prompt text, which
produces a self-sustaining speak -> echo -> barge-in -> speak loop.
"""

import numpy as np
import pytest

from core.openai_stt import OpenAIWhisperSTT


class _FakeTranscriptions:
    def __init__(self, sink):
        self.sink = sink

    def create(self, **params):
        self.sink.append(params)
        class R:
            text = "hello"
            segments = None
        return R()


class _FakeClient:
    def __init__(self, sink):
        self.audio = type("A", (), {"transcriptions": _FakeTranscriptions(sink)})()


@pytest.fixture
def stt_and_calls(monkeypatch):
    monkeypatch.setattr(OpenAIWhisperSTT, "_init_client", lambda self: None)
    stt = OpenAIWhisperSTT(model="gpt-4o-mini-transcribe")
    calls = []
    stt._client = _FakeClient(calls)
    return stt, calls


AUDIO = np.zeros(16000, dtype=np.float32)


def test_no_prompt_sent_when_profile_is_empty(stt_and_calls):
    stt, calls = stt_and_calls
    stt.prompt = ""
    stt.transcribe(AUDIO, "en", initial_prompt=None)
    assert "prompt" not in calls[-1]


def test_configured_prompt_is_forwarded(stt_and_calls):
    stt, calls = stt_and_calls
    stt.transcribe(AUDIO, "en", initial_prompt="kitchen timer, oven")
    assert calls[-1]["prompt"] == "kitchen timer, oven"


def test_explicit_empty_prompt_overrides_constructor_default(stt_and_calls):
    """The regression: a constructor prompt must not survive an empty profile."""
    stt, calls = stt_and_calls
    stt.prompt = "ARGO, Tommy, Home Assistant, Jellyfin"
    stt.transcribe(AUDIO, "en", initial_prompt="")
    assert "prompt" not in calls[-1]


def test_constructor_prompt_used_only_when_caller_supplies_none(stt_and_calls):
    stt, calls = stt_and_calls
    stt.prompt = "fallback terms"
    stt.transcribe(AUDIO, "en")           # no initial_prompt kwarg at all
    assert calls[-1]["prompt"] == "fallback terms"


def test_cloud_engine_loads_without_a_hardcoded_prompt(monkeypatch):
    """stt_engine_manager must not inject its own biasing terms."""
    import core.stt_engine_manager as sem

    captured = {}

    class _Spy:
        def __init__(self, **kw):
            captured.update(kw)

    # _load_openai_cloud imports the class inside the function, so patch it at
    # the source module.
    monkeypatch.setattr("core.openai_stt.OpenAIWhisperSTT", _Spy)

    mgr = sem.STTEngineManager.__new__(sem.STTEngineManager)
    mgr.model_size = "gpt-4o-mini-transcribe"
    import logging
    mgr.logger = logging.getLogger("test")
    mgr._load_openai_cloud()

    assert captured.get("prompt") == "", f"hardcoded prompt leaked: {captured.get('prompt')!r}"
