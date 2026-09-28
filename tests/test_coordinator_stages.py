from io import BytesIO
from types import SimpleNamespace

import numpy as np
from scipy.io import wavfile

from core.coordinator_stages import capture_audio_stage, transcribe_audio_stage


class Probe:
    def __init__(self):
        self.marks = []

    def mark(self, name):
        self.marks.append(name)


class Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def debug(self, message):
        self.messages.append(("debug", message))


def make_coordinator():
    coordinator = SimpleNamespace()
    coordinator.interaction_count = 3
    coordinator.MAX_RECORDING_DURATION = 10
    coordinator.SILENCE_DURATION = 1.5
    coordinator.AUDIO_SAMPLE_RATE = 16000
    coordinator.current_probe = Probe()
    coordinator.logger = Logger()
    coordinator.on_recording_start = None
    coordinator.on_recording_stop = None
    coordinator.audio = np.array([0, 100, -100, 200], dtype=np.int16)
    coordinator._record_with_silence_detection = (
        lambda initial_frames=None: coordinator.audio
    )
    return coordinator


def test_capture_stage_preserves_callbacks_probe_order_and_wav_format():
    coordinator = make_coordinator()
    callbacks = []
    coordinator.on_recording_start = lambda: callbacks.append("start")
    coordinator.on_recording_stop = lambda: callbacks.append("stop")

    payload = capture_audio_stage(coordinator, initial_frames=[b"seed"])

    rate, decoded = wavfile.read(BytesIO(payload))
    assert rate == 16000
    assert np.array_equal(decoded, coordinator.audio)
    assert callbacks == ["start", "stop"]
    assert coordinator.current_probe.marks == ["recording_start", "recording_end"]


def test_capture_stage_logs_callback_errors_but_keeps_recording():
    coordinator = make_coordinator()
    coordinator.on_recording_start = lambda: (_ for _ in ()).throw(
        RuntimeError("start failed")
    )
    coordinator.on_recording_stop = lambda: (_ for _ in ()).throw(
        RuntimeError("stop failed")
    )

    payload = capture_audio_stage(coordinator)

    assert payload.startswith(b"RIFF")
    debug_messages = [message for level, message in coordinator.logger.messages if level == "debug"]
    assert any("start failed" in message for message in debug_messages)
    assert any("stop failed" in message for message in debug_messages)


def test_transcription_stage_marks_probe_and_updates_observer_state():
    coordinator = make_coordinator()
    coordinator.stt = SimpleNamespace(
        transcribe=lambda payload, rate: "Exact Raw Transcript"
    )
    coordinator.get_dynamic_timeout = lambda text: 4.25
    before = coordinator.current_probe.marks.copy()

    result = transcribe_audio_stage(coordinator, b"wav")

    assert result == "Exact Raw Transcript"
    assert coordinator.current_probe.marks == [*before, "stt_start", "stt_end"]
    assert coordinator._last_transcript == "Exact Raw Transcript"
    assert coordinator._last_wake_timestamp is not None
    assert coordinator.dynamic_silence_timeout == 4.25
    assert ("info", "[STT RAW] 'Exact Raw Transcript'") in coordinator.logger.messages
