import numpy as np
from core.pipeline import ArgoPipeline
from core.memory_store import MemoryStore


class DummyAudio:
    def acquire_audio(self, *args, **kwargs):
        return True
    def release_audio(self, *args, **kwargs):
        return True
    def stop_playback(self, *args, **kwargs):
        return True
    def force_release_audio(self, *args, **kwargs):
        return True


def make_pipeline(tmp_path):
    logs = []

    def broadcast(kind, payload):
        if kind == "log":
            logs.append(payload)

    pipeline = ArgoPipeline(DummyAudio(), broadcast)
    pipeline._memory_store = MemoryStore(tmp_path / "memory.db")
    return pipeline


def test_audio_reject_below_rms(tmp_path):
    p = make_pipeline(tmp_path)
    reject, reason = p._should_reject_audio(rms=0.0001, silence_ratio=0.1)
    assert reject is True
    assert reason == "below_rms_threshold"


def test_audio_reject_silence_ratio(tmp_path):
    p = make_pipeline(tmp_path)
    reject, reason = p._should_reject_audio(rms=0.01, silence_ratio=0.95)
    assert reject is True
    assert reason == "silence_detected"


def test_audio_accept_valid(tmp_path):
    p = make_pipeline(tmp_path)
    reject, reason = p._should_reject_audio(rms=0.02, silence_ratio=0.2)
    assert reject is False
    assert reason == ""


def test_initial_prompt_loaded(tmp_path):
    p = make_pipeline(tmp_path)
    # Default profile is general, prompt may be empty
    assert p._stt_prompt_profile in {"general", "technical"}
    assert isinstance(p._stt_initial_prompt, str)
