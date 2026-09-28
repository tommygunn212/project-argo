"""Stream lifecycle tests for coordinator speech-onset waiting."""

import threading
from unittest.mock import Mock

import numpy as np

from core.coordinator import Coordinator


class FakeStream:
    def __init__(self, frames=None, error=None):
        self.frames = iter(frames or [])
        self.error = error
        self.start = Mock()
        self.stop = Mock()
        self.close = Mock()

    def read(self, _samples):
        if self.error:
            raise self.error
        return next(self.frames), None


def _coordinator():
    coordinator = Coordinator.__new__(Coordinator)
    coordinator.AUDIO_SAMPLE_RATE = 100
    coordinator.PRE_ROLL_BUFFER_MS_MAX = 200
    coordinator.RMS_SPEECH_THRESHOLD = 0.02
    coordinator.input_device_index = 3
    coordinator.AUDIO_STATE_SPEAKING = "SPEAKING"
    coordinator._audio_state = "IDLE"
    coordinator._input_stop_event = threading.Event()
    coordinator._input_stream = None
    coordinator._input_stream_active = False
    coordinator.logger = Mock()
    return coordinator


def _frame(amplitude):
    return np.full((10, 1), amplitude, dtype=np.int16)


def test_speech_wait_does_not_open_input_while_output_is_speaking(monkeypatch):
    coordinator = _coordinator()
    coordinator._audio_state = coordinator.AUDIO_STATE_SPEAKING
    factory = Mock()
    monkeypatch.setattr("core.coordinator.sd.InputStream", factory)

    assert coordinator._wait_for_speech_start(None) is None
    factory.assert_not_called()


def test_speech_wait_returns_bounded_preroll_and_closes_stream(monkeypatch):
    coordinator = _coordinator()
    stream = FakeStream([_frame(100), _frame(200), _frame(1000)])
    factory = Mock(return_value=stream)
    monkeypatch.setattr("core.coordinator.sd.InputStream", factory)

    frames = coordinator._wait_for_speech_start(None)

    assert len(frames) == 2
    assert np.array_equal(frames[0], _frame(200))
    assert np.array_equal(frames[1], _frame(1000))
    factory.assert_called_once_with(
        channels=1, samplerate=100, dtype=np.int16, device=3
    )
    stream.start.assert_called_once_with()
    stream.stop.assert_called_once_with()
    stream.close.assert_called_once_with()
    assert coordinator._input_stream is None
    assert coordinator._input_stream_active is False


def test_stop_request_aborts_after_open_and_still_closes_stream(monkeypatch):
    coordinator = _coordinator()
    coordinator._input_stop_event.set()
    stream = FakeStream([_frame(1000)])
    monkeypatch.setattr("core.coordinator.sd.InputStream", Mock(return_value=stream))

    assert coordinator._wait_for_speech_start(None) is None
    stream.stop.assert_called_once_with()
    stream.close.assert_called_once_with()
    assert coordinator._input_stream is None
    assert coordinator._input_stream_active is False


def test_stream_read_failure_is_contained_and_cleanup_runs(monkeypatch):
    coordinator = _coordinator()
    stream = FakeStream(error=RuntimeError("device lost"))
    monkeypatch.setattr("core.coordinator.sd.InputStream", Mock(return_value=stream))

    assert coordinator._wait_for_speech_start(None) is None
    stream.stop.assert_called_once_with()
    stream.close.assert_called_once_with()
    assert any(
        "device lost" in call.args[0]
        for call in coordinator.logger.debug.call_args_list
    )
