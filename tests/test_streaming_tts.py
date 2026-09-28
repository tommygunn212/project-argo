import logging
import queue
import threading
from types import SimpleNamespace

from core.streaming_tts import consume_tts_sentences


class _Audio:
    def __init__(self):
        self.acquired = []
        self.released = []

    def acquire_audio(self, owner, **kwargs):
        self.acquired.append((owner, kwargs))

    def release_audio(self, owner, **kwargs):
        self.released.append((owner, kwargs))


class _EdgeTTS:
    def __init__(self):
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)


def _host(interaction_id="turn-1"):
    edge = _EdgeTTS()
    host = SimpleNamespace(
        audio=_Audio(),
        broadcast=lambda *_: None,
        current_interaction_id=interaction_id,
        current_voice_key="default",
        is_speaking=False,
        logger=logging.getLogger("test.streaming_tts"),
        openai_voices={},
        stop_signal=threading.Event(),
        tts_finished_at=0.0,
        voices={},
        _edge_tts=edge,
        _openai_tts=None,
        _tts_model="unused",
        _TTS_INSTRUCTIONS="unused",
        transitions=[],
        timeline=[],
    )
    host.transition_state = lambda state, **kwargs: host.transitions.append((state, kwargs))
    host._record_timeline = lambda event, **kwargs: host.timeline.append((event, kwargs))
    return host, edge


def _consume(host, *items, interaction_id="turn-1"):
    sentences = queue.Queue()
    for item in items:
        sentences.put(item)
    started = threading.Event()
    errors = []
    consume_tts_sentences(
        host,
        sentences,
        interaction_id=interaction_id,
        tts_engine="edge",
        chinese_lesson=False,
        tts_started=started,
        tts_errors=errors,
    )
    return started, errors


def test_edge_stream_acquires_plays_and_releases_audio():
    host, edge = _host()

    started, errors = _consume(host, "First.", "Second.", None)

    assert started.is_set()
    assert errors == []
    assert edge.spoken == ["First.", "Second."]
    assert host.audio.acquired == [("TTS", {"interaction_id": "turn-1"})]
    assert host.audio.released == [("TTS", {"interaction_id": "turn-1"})]
    assert host.is_speaking is False
    assert [event for event, _ in host.timeline] == ["TTS_START", "TTS_DONE"]


def test_stale_turn_does_not_release_audio_owned_by_new_turn():
    host, edge = _host(interaction_id="turn-2")

    started, errors = _consume(host, "Old turn.", None, interaction_id="turn-1")

    assert started.is_set()
    assert errors == []
    assert edge.spoken == ["Old turn."]
    assert host.audio.acquired == [("TTS", {"interaction_id": "turn-1"})]
    assert host.audio.released == []
    assert host.is_speaking is True
    assert [event for event, _ in host.timeline] == ["TTS_START"]
