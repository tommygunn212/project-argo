from io import BytesIO
from types import SimpleNamespace

import numpy as np
from scipy.io import wavfile

from core.coordinator_stages import (
    capture_audio_stage,
    process_transcript_stage,
    transcribe_audio_stage,
)


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


class Memory:
    def __init__(self):
        self.calls = []

    def append(self, **kwargs):
        self.calls.append(kwargs)


def make_transcript_coordinator(confidence=0.9):
    coordinator = make_coordinator()
    coordinator.last_response_text = ""
    coordinator._last_built_script = None
    coordinator._similarity_ratio = lambda _left, _right: 0.0
    coordinator.stt = SimpleNamespace(
        get_last_metrics=lambda: {"confidence": confidence}
    )
    coordinator._low_conf_notice_given = False
    coordinator.runtime_overrides = {"tts_enabled": True}
    coordinator.interaction_id = "interaction-1"
    coordinator.spoken = []
    coordinator._safe_speak = lambda text, **kwargs: coordinator.spoken.append(
        (text, kwargs)
    )
    coordinator.memory = Memory()
    coordinator.builder = SimpleNamespace(test_run=lambda _path: "script output")
    coordinator.generator = SimpleNamespace(generate=lambda _intent, _memory: "analysis")
    return coordinator


def test_passive_transcript_returns_false_without_parsing_or_count_change():
    coordinator = make_transcript_coordinator()

    result = process_transcript_stage(
        coordinator, "heard words", {"force_passive_listening": True}
    )

    assert result.continue_processing is False
    assert result.interaction_result is False
    assert coordinator.interaction_count == 3


def test_self_echo_decrements_iteration_and_stops_processing():
    coordinator = make_transcript_coordinator()
    coordinator.last_response_text = "same words"
    coordinator._similarity_ratio = lambda _left, _right: 0.95

    result = process_transcript_stage(coordinator, "same words", {})

    assert result.continue_processing is False
    assert result.interaction_result is False
    assert coordinator.interaction_count == 2


def test_empty_transcript_decrements_iteration_and_stops_processing():
    coordinator = make_transcript_coordinator()

    result = process_transcript_stage(coordinator, "   ", {})

    assert result.continue_processing is False
    assert coordinator.interaction_count == 2


def test_valid_transcript_normalizes_text_and_exports_confidence():
    coordinator = make_transcript_coordinator(confidence=0.82)

    result = process_transcript_stage(coordinator, "system stats", {})

    assert result.continue_processing is True
    assert result.interaction_result is False
    assert result.text
    assert result.stt_confidence == 0.82


def test_very_low_confidence_text_is_rejected_with_one_notice():
    coordinator = make_transcript_coordinator(confidence=0.05)

    result = process_transcript_stage(coordinator, "unclear phrase", {})

    assert result.continue_processing is False
    assert coordinator.interaction_count == 2
    assert len(coordinator.spoken) == 1
    assert coordinator._low_conf_notice_given is True


def test_low_confidence_count_is_allowed_to_continue():
    coordinator = make_transcript_coordinator(confidence=0.05)

    result = process_transcript_stage(coordinator, "count to five", {})

    assert result.continue_processing is True
    assert result.stt_confidence == 0.05
    assert coordinator.spoken == []


def test_script_rerun_is_a_successful_terminal_interaction():
    coordinator = make_transcript_coordinator()
    coordinator._last_built_script = "sandbox/test.py"

    result = process_transcript_stage(coordinator, "run it", {})

    assert result.continue_processing is False
    assert result.interaction_result is True
    assert coordinator.last_response_text == "analysis"
    assert coordinator.spoken == [("analysis", {"interaction_id": "interaction-1"})]
    assert coordinator.memory.calls[0]["parsed_intent"] == "develop"
