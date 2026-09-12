import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from scipy.signal import upfirdn

from core.bounded_context import BoundedContext
from core.openai_tts import OpenAIRealtimeTTS
from core.streaming_resampler import StreamingResampler
from core.voice_clients import VoiceClients


@pytest.mark.parametrize("rate", [16000, 24000, 44100, 48000])
def test_resampling_is_independent_of_network_chunk_boundaries(rate):
    samples = np.random.default_rng(9).normal(size=4983).astype(np.float32)
    resampler = StreamingResampler(24000, rate)
    expected = samples if resampler.taps is None else upfirdn(
        resampler.taps, samples, up=resampler.up, down=resampler.down)
    pieces = []
    for i in range(0, len(samples), 37):
        pieces.append(resampler.process(samples[i:i + 37]))
    pieces.append(resampler.process([], final=True))
    np.testing.assert_allclose(np.concatenate(pieces), expected, atol=2e-6)
    assert len(resampler.pending) == 0


def fake_tts(monkeypatch, chunks, on_write=None):
    import sounddevice
    tts = OpenAIRealtimeTTS.__new__(OpenAIRealtimeTTS)
    tts.voice, tts.model, tts.speed = "nova", "tts-1", 1
    tts._instructions = None
    tts._cancel_lock = threading.Lock()
    tts._playback_lock = threading.Lock()
    tts._cancel_generation = 0
    tts._stop_requested = tts._is_playing = False
    tts._audio_device, tts._device_sample_rate = 4, 24000
    tts._active_stream = None
    events = []

    class Response:
        def __enter__(self):
            events.append("response_open")
            return self

        def __exit__(self, *args):
            events.append("response_closed")

        def iter_bytes(self, **kwargs):
            for chunk in chunks():
                yield chunk
            events.append("response_eof")

    class Output:
        def __init__(self, **kwargs):
            assert kwargs["device"] == 4
            events.append("output_open")

        def start(self):
            events.append("start")

        def write(self, samples):
            events.append(("write", samples.copy()))
            if on_write:
                on_write(tts)
            return False

        def stop(self):
            events.append("drain")

        def abort(self):
            events.append("abort")

        def close(self):
            events.append("output_closed")

    create = Mock(side_effect=lambda **kwargs: Response())
    tts._client = SimpleNamespace(audio=SimpleNamespace(speech=SimpleNamespace(
        with_streaming_response=SimpleNamespace(create=create),
        create=Mock(side_effect=AssertionError("Buffered speech.create must not be used")))))
    monkeypatch.setattr(sounddevice, "OutputStream", Output)
    monkeypatch.setattr(sounddevice, "stop", Mock(side_effect=AssertionError("Do not stop other audio")))
    return tts, events, create


def writes(events):
    return [event[1] for event in events if isinstance(event, tuple)]


def test_speech_writes_before_http_eof_and_handles_odd_chunks(monkeypatch):
    pcm = np.arange(4501, dtype="<i2").tobytes()
    def chunks():
        yield pcm[:4001]
        assert writes(events), "First audio must play before the rest is downloaded"
        yield pcm[4001:8003]
        yield pcm[8003:]
    tts, events, _ = fake_tts(monkeypatch, chunks)
    tts.speak("hello")
    np.testing.assert_array_equal(np.concatenate(writes(events)).ravel(),
                                  np.arange(4501, dtype=np.float32) / 32768)
    assert "drain" in events and "response_closed" in events
    assert not tts.is_playing and tts._active_stream is None


def test_short_speech_uses_owned_stream_not_global_play(monkeypatch):
    tts, events, _ = fake_tts(monkeypatch, lambda: iter([b"\x01\x00" * 12]))
    tts.speak("short")
    assert sum(len(x) for x in writes(events)) == 12
    assert "drain" in events


def test_interrupt_aborts_own_stream_closes_http_and_does_not_drain(monkeypatch):
    tts, events, _ = fake_tts(monkeypatch, lambda: iter([b"\x01\x00" * 4000] * 3),
                               on_write=lambda tts: tts.stop())
    tts.speak("interrupt me")
    assert len(writes(events)) == 1
    assert "abort" in events and "response_closed" in events
    assert "drain" not in events and not tts.is_playing


def test_stream_error_propagates_but_releases_resources(monkeypatch):
    def chunks():
        yield b"\x01\x00" * 4000
        raise TimeoutError("stalled network")
    tts, events, _ = fake_tts(monkeypatch, chunks)
    with pytest.raises(TimeoutError):
        tts.speak("timeout")
    assert "output_closed" in events and "response_closed" in events
    assert not tts.is_playing


def test_prefetch_reuses_client_and_cancels_without_another_request(monkeypatch):
    tts, events, create = fake_tts(monkeypatch, lambda: iter([b"\x01\x00"] * 3))
    generation = tts.begin_response()
    assert tts.synthesize("one", generation) == b"\x01\x00" * 3
    assert tts.synthesize("two", generation) == b"\x01\x00" * 3
    tts.stop()
    assert tts.synthesize("cancelled", generation) is None
    assert create.call_count == 2 and events.count("response_closed") == 2


def test_tts_client_has_timeout_no_retries_and_selected_device(monkeypatch):
    import openai
    import sounddevice
    factory, query = Mock(), Mock(return_value={"default_samplerate": 44100, "name": "selected"})
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr(openai, "OpenAI", factory)
    monkeypatch.setattr(sounddevice, "query_devices", query)
    tts = OpenAIRealtimeTTS(output_device=4, timeout_seconds=7)
    factory.assert_called_once_with(api_key="test-only", timeout=7.0, max_retries=0)
    query.assert_called_once_with(4, "output")
    assert tts._audio_device == 4


def test_context_deadline_does_not_wait_for_shutdown_or_accumulate_jobs():
    context, release, entered = BoundedContext(), threading.Event(), threading.Event()
    calls = []
    def slow():
        calls.append(1)
        entered.set()
        release.wait(2)
        return "stale"
    try:
        start = time.monotonic()
        result, missing = context.fetch({"rag": slow, "memory": lambda: "fresh"}, timeout=0.04)
        assert time.monotonic() - start < 0.4
        assert entered.is_set() and result == {"memory": "fresh"} and missing == ["rag"]
        for _ in range(3):
            result, missing = context.fetch({"rag": slow, "memory": lambda: "new"}, timeout=0.04)
            assert result == {"memory": "new"} and missing == ["rag"]
        assert len(calls) == 1
    finally:
        release.set()
        context.close()


def test_context_exception_is_optional_not_a_failed_turn():
    context = BoundedContext()
    try:
        result, missing = context.fetch({"rag": lambda: 1/0, "memory": lambda: "ok"})
        assert result == {"memory": "ok"} and missing == ["rag"]
    finally:
        context.close()


def test_llm_client_reused_and_timeout_reaches_sdk(monkeypatch):
    import openai
    factory = Mock()
    monkeypatch.setattr(openai, "OpenAI", factory)
    clients = VoiceClients({"llm": {"timeout_seconds": 9}})
    assert clients.get("openai") is clients.get("openai")
    factory.assert_called_once_with(timeout=9.0, max_retries=0)
    clients.close()


def test_stt_timeout_is_explicit_and_does_not_automatically_retry(monkeypatch):
    import openai
    from core.openai_stt import OpenAIWhisperSTT
    factory = Mock()
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr(openai, "OpenAI", factory)
    OpenAIWhisperSTT(timeout_seconds=8)
    factory.assert_called_once_with(api_key="test-only", timeout=8.0, max_retries=0)


def test_failed_transcription_releases_audio_lock_and_returns_to_listening():
    from core.pipeline import ArgoPipeline
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.processing_lock = threading.Lock()
    pipeline.stop_signal = threading.Event()
    pipeline.logger = logging.getLogger("test")
    pipeline.current_state = "LISTENING"
    pipeline.is_speaking = False
    pipeline.audio = SimpleNamespace(acquire_audio=Mock(), release_audio=Mock())
    pipeline.broadcast = Mock()
    pipeline._record_timeline = Mock()
    pipeline.transcribe = Mock(side_effect=TimeoutError("offline"))
    pipeline.transition_state = lambda state, **kwargs: setattr(pipeline, "current_state", state)
    pipeline.run_interaction(np.zeros(512), interaction_id="failed")
    pipeline.audio.release_audio.assert_called_once_with("STT", interaction_id="failed")
    assert not pipeline.processing_lock.locked()
    assert pipeline.current_state == "LISTENING"
    pipeline.current_state = "THINKING"
    pipeline.stop_signal.set()
    pipeline._recover_failed_turn("failed")
    assert pipeline.current_state == "THINKING"  # do not override a user's stop
    pipeline.stop_signal.clear()
    pipeline.current_interaction_id = "newer"
    pipeline._recover_failed_turn("failed")
    assert pipeline.current_state == "THINKING"


def test_capture_queue_is_bounded_keeps_newest_and_reports_off_callback(monkeypatch):
    import sounddevice
    from core.audio_manager import AudioManager
    monkeypatch.setattr(sounddevice, "query_devices", lambda: [])
    audio = AudioManager()
    audio.logger = Mock()
    for value in range(80):
        audio._audio_callback(np.full((512, 1), value), 512, None, value == 1)
    assert audio.input_queue.qsize() == 32
    assert audio.input_dropped_frames == 48 and audio.input_status_events == 1
    audio.logger.warning.assert_not_called()
    frame = audio.read_frame(timeout=0)
    assert frame[0, 0] == 48
    audio.logger.warning.assert_called_once()


def test_late_sentence_prefetch_overlaps_current_playback():
    from core.pipeline import ArgoPipeline
    current_playing, prefetched = threading.Event(), threading.Event()
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.llm_enabled = True
    pipeline._config = {"llm": {"backend": "openai", "model": "test"}}
    pipeline._tts_engine, pipeline._openai_tts = "openai", Mock()
    pipeline.stop_signal = threading.Event()
    pipeline._openai_tts.begin_response.return_value = 1
    pipeline._openai_tts.is_cancelled.return_value = False
    pipeline._openai_tts.synthesize.side_effect = lambda *args: (prefetched.set(), b"pcm")[1]
    def speak(*args, **kwargs):
        current_playing.set()
        assert prefetched.wait(2), "Late sentence should prefetch while first sentence plays"
    pipeline._openai_tts.speak.side_effect = speak
    pipeline.logger = logging.getLogger("test")
    pipeline.audio = Mock()
    pipeline.transition_state = Mock()
    pipeline.broadcast = Mock()
    pipeline._record_timeline = Mock()
    pipeline.current_interaction_id = "overlap"
    pipeline._resolve_personality_mode = lambda: "plain"
    pipeline._is_serious = lambda text: False
    pipeline._conversation_buffer = SimpleNamespace(as_messages=lambda: [])
    pipeline._get_spoken_response_controls = lambda: {"temperature": 0, "max_tokens": 100, "max_sentences": 5}
    pipeline._build_llm_prompt = lambda *a, **kw: "test"
    pipeline._build_spoken_style_block = lambda *a: ""
    pipeline._get_system_message = lambda *a: ""
    pipeline._sanitize_tts_text = lambda text, **kw: text
    pipeline._strip_prompt_artifacts = lambda text: text
    pipeline._strip_disallowed_phrases = lambda text: text
    pipeline._pop_stream_chunk = lambda text, **kw: (text, "") if text.endswith(".") else ("", text)
    closed = []
    def llm():
        try:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="First sentence."))])
            assert current_playing.wait(2)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Second sentence."))])
        finally:
            closed.append(True)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: llm())))
    pipeline._voice_clients = SimpleNamespace(get=lambda backend: client)
    result = pipeline._generate_and_speak_streamed("test", interaction_id="overlap")
    assert result == "First sentence.Second sentence."
    assert prefetched.is_set() and closed
    pipeline._openai_tts.play_pcm.assert_called_once_with(b"pcm", generation=1)
    pipeline.audio.release_audio.assert_called_once_with("TTS", interaction_id="overlap")
