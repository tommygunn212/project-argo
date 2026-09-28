from unittest.mock import Mock

import numpy as np
import pytest

from core.coordinator_recording import RecordingConfig, RecordingHooks, record_with_silence_detection


class FakeStream:
    def __init__(self, chunks=None, error=None):
        self.chunks = iter(chunks or [])
        self.error = error
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self):
        self.started = True

    def read(self, count):
        if self.error:
            raise self.error
        return next(self.chunks), None

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FakeVad:
    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.reset_called = False

    def reset(self):
        self.reset_called = True

    def is_speech(self, chunk):
        return next(self.decisions)


def config():
    return RecordingConfig(
        sample_rate=100,
        minimum_duration=0.1,
        dynamic_silence_timeout=0.2,
        maximum_duration=1.0,
        rms_speech_threshold=0.01,
        silence_threshold=0.005,
        silence_timeout_label=0.2,
        record_debug=False,
        input_device_index=4,
    )


def hooks(vad, states, events, *, abort=False):
    return RecordingHooks(
        logger=Mock(),
        should_abort=lambda: abort,
        speech_gate=lambda: vad,
        get_preroll=Mock(return_value=[]),
        set_stream_state=lambda stream, active: states.append((stream, active)),
        event_logger=events.append,
        last_transcript=lambda: "",
    )


def test_capture_stops_after_post_speech_silence_and_normalizes():
    chunks = [
        np.full((10, 1), 1000, dtype=np.int16),
        np.zeros((10, 1), dtype=np.int16),
        np.zeros((10, 1), dtype=np.int16),
    ]
    stream = FakeStream(chunks)
    vad = FakeVad([True, False, False])
    states, events = [], []

    audio = record_with_silence_detection(
        config(),
        hooks(vad, states, events),
        stream_factory=lambda **kwargs: stream,
        device_query=lambda: [],
    )

    assert audio.shape == (30, 1)
    assert int(audio.max()) == 32767
    assert vad.reset_called is True
    assert stream.started and stream.stopped and stream.closed
    assert events == ["MIC OPEN", "MIC CLOSE"]
    assert states == [(stream, True), (None, False)]


def test_abort_closes_stream_without_reading():
    stream = FakeStream(error=AssertionError("read should not run"))
    states, events = [], []

    audio = record_with_silence_detection(
        config(),
        hooks(FakeVad([]), states, events, abort=True),
        stream_factory=lambda **kwargs: stream,
        device_query=lambda: [],
    )

    assert audio.size == 0
    assert stream.stopped and stream.closed
    assert states[-1] == (None, False)


def test_read_error_still_closes_and_clears_stream_state():
    stream = FakeStream(error=RuntimeError("mic failed"))
    states, events = [], []

    with pytest.raises(RuntimeError, match="mic failed"):
        record_with_silence_detection(
            config(),
            hooks(FakeVad([]), states, events),
            stream_factory=lambda **kwargs: stream,
            device_query=lambda: [],
        )

    assert stream.stopped and stream.closed
    assert events[-1] == "MIC CLOSE"
    assert states[-1] == (None, False)


def test_initial_frames_bypass_trigger_preroll_lookup():
    stream = FakeStream()
    states, events = [], []
    recording_hooks = hooks(FakeVad([]), states, events, abort=True)
    initial = [np.full((5, 1), 200, dtype=np.int16)]

    audio = record_with_silence_detection(
        config(),
        recording_hooks,
        stream_factory=lambda **kwargs: stream,
        device_query=lambda: [],
        initial_frames=initial,
    )

    recording_hooks.get_preroll.assert_not_called()
    assert audio.shape == (5, 1)
