import threading

import numpy as np
import pytest

from core.openai_tts import OpenAIRealtimeTTS


def _tts_without_io() -> OpenAIRealtimeTTS:
    tts = OpenAIRealtimeTTS.__new__(OpenAIRealtimeTTS)
    tts.voice = "nova"
    tts.model = "tts-1"
    tts.speed = 1.0
    tts._client = None
    tts._stop_requested = False
    tts._cancel_lock = threading.Lock()
    tts._playback_lock = threading.Lock()
    tts._cancel_generation = 0
    tts._is_playing = False
    tts._audio_device = None
    tts._device_sample_rate = 24000
    tts._interrupt_suppress_until = 0.0
    tts._instructions = None
    return tts


def test_stop_invalidates_current_generation():
    tts = _tts_without_io()

    old_generation = tts.begin_response()
    assert not tts.is_cancelled(old_generation)

    tts.stop()

    assert tts.is_cancelled(old_generation)
    assert tts.is_cancelled()

    new_generation = tts.begin_response()

    assert not tts.is_cancelled(new_generation)
    assert tts.is_cancelled(old_generation)


def test_play_pcm_does_not_clear_cancelled_generation():
    tts = _tts_without_io()
    generation = tts.begin_response()
    tts.stop()

    tts.play_pcm(b"\x00\x00" * 32, generation=generation)

    assert tts.is_cancelled(generation)
    assert not tts.is_playing


def test_synthesize_skips_after_stop_without_api_call():
    tts = _tts_without_io()
    generation = tts.begin_response()
    tts.stop()

    assert tts.synthesize("this should not call OpenAI", generation=generation) is None


@pytest.mark.parametrize("mode", ["normal", "interrupt", "write_error", "observer_error"])
def test_avatar_meter_observes_playback_and_always_clears(monkeypatch, mode):
    import sounddevice as sd

    tts = _tts_without_io()
    levels = []
    writes = []

    def report(level):
        levels.append(level)
        if mode == "observer_error":
            raise RuntimeError("UI disconnected")

    class FakeStream:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def write(self, samples):
            writes.append(samples.copy())
            if mode == "interrupt":
                tts.stop()
            if mode == "write_error":
                raise RuntimeError("Device disconnected")
            return False

        def stop(self):
            pass

        def abort(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(sd, "OutputStream", FakeStream)
    tts._on_audio_level = report
    pcm = np.full(2400, 4096, dtype="<i2").tobytes()
    if mode == "write_error":
        with pytest.raises(RuntimeError, match="Device disconnected"):
            tts.play_pcm(pcm)
    else:
        tts.play_pcm(pcm)
    assert writes
    assert levels[-1] == 0
    assert not tts.is_playing
    if mode in ("normal", "observer_error"):
        assert any(abs(level - 0.125) < 0.001 for level in levels)
    else:
        assert all(level == 0 for level in levels)
