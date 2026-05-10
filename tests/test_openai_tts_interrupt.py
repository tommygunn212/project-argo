import threading

from core.openai_tts import OpenAIRealtimeTTS


def _tts_without_io() -> OpenAIRealtimeTTS:
    tts = OpenAIRealtimeTTS.__new__(OpenAIRealtimeTTS)
    tts.voice = "nova"
    tts.model = "tts-1"
    tts.speed = 1.0
    tts._client = None
    tts._stop_requested = False
    tts._cancel_lock = threading.Lock()
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
