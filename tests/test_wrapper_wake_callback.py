"""Behavior tests for the legacy wrapper wake-word callback."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

from wrapper import argo


def _install_voice_input(monkeypatch, *, audio=None, transcript="hello"):
    record = Mock(return_value=[1] if audio is None else audio)
    transcribe = Mock(return_value=transcript)
    monkeypatch.setitem(
        sys.modules,
        "voice_input",
        SimpleNamespace(
            record_audio_on_wake_word=record,
            transcribe_audio=transcribe,
        ),
    )
    return record, transcribe


def _configure(monkeypatch, state="LISTENING", wake_result=True):
    state_machine = SimpleNamespace(
        current_state=state,
        wake=Mock(return_value=wake_result),
    )
    parser = Mock()
    request_factory = Mock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(argo, "WAKE_WORD_DETECTOR_AVAILABLE", True)
    monkeypatch.setattr(argo, "_state_machine", state_machine)
    monkeypatch.setattr(argo, "_command_parser", parser)
    monkeypatch.setattr(argo, "WakeWordRequest", request_factory)
    return state_machine, parser, request_factory


def test_wake_callback_ignores_non_listening_state(monkeypatch):
    state_machine, parser, _ = _configure(monkeypatch, state="THINKING")
    record, transcribe = _install_voice_input(monkeypatch)

    argo._on_wake_word_detected()

    state_machine.wake.assert_not_called()
    record.assert_not_called()
    transcribe.assert_not_called()
    parser.process_wake_word_event.assert_not_called()


def test_sleep_wake_rejection_stops_before_recording(monkeypatch):
    state_machine, parser, _ = _configure(
        monkeypatch, state="SLEEP", wake_result=False
    )
    record, _ = _install_voice_input(monkeypatch)

    argo._on_wake_word_detected()

    state_machine.wake.assert_called_once_with()
    record.assert_not_called()
    parser.process_wake_word_event.assert_not_called()


def test_empty_wake_recording_stops_before_transcription(monkeypatch):
    _, parser, _ = _configure(monkeypatch)
    record, transcribe = _install_voice_input(monkeypatch, audio=[])

    argo._on_wake_word_detected()

    record.assert_called_once_with()
    transcribe.assert_not_called()
    parser.process_wake_word_event.assert_not_called()


def test_wake_callback_records_transcribes_and_dispatches_request(monkeypatch):
    _, parser, request_factory = _configure(monkeypatch)
    record, transcribe = _install_voice_input(
        monkeypatch, audio=[1, 2], transcript="open music"
    )

    argo._on_wake_word_detected()

    record.assert_called_once_with()
    transcribe.assert_called_once_with([1, 2])
    request_factory.assert_called_once_with(confidence=0.95)
    parser.process_wake_word_event.assert_called_once()
    request = parser.process_wake_word_event.call_args.args[0]
    assert request.confidence == 0.95


def test_wake_callback_contains_voice_input_failure(monkeypatch):
    _, parser, _ = _configure(monkeypatch)
    record, _ = _install_voice_input(monkeypatch)
    record.side_effect = RuntimeError("microphone offline")
    error = Mock()
    monkeypatch.setattr(argo.logger, "error", error)

    argo._on_wake_word_detected()

    assert any("microphone offline" in call.args[0] for call in error.call_args_list)
    parser.process_wake_word_event.assert_not_called()
