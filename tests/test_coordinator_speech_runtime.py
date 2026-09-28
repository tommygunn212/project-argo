"""Audio-ownership contract tests for coordinator speech playback."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

from core.coordinator import Coordinator


def _coordinator():
    coordinator = Coordinator.__new__(Coordinator)
    coordinator.logger = Mock()
    coordinator._pause_trigger_for_tts = Mock()
    coordinator._resume_trigger_after_tts = Mock()
    coordinator.acquire_audio = Mock()
    coordinator.release_audio = Mock()
    coordinator.sink = SimpleNamespace(speak=Mock())
    coordinator.interaction_id = 17
    coordinator._is_speaking = threading.Event()
    coordinator._is_speaking.set()
    return coordinator


def test_coordinator_speech_pauses_input_owns_audio_and_restores_everything():
    coordinator = _coordinator()

    coordinator._speak_with_interrupt_detection("hello")

    coordinator._pause_trigger_for_tts.assert_called_once_with()
    coordinator.acquire_audio.assert_called_once_with("TTS")
    coordinator.sink.speak.assert_called_once_with("hello", interaction_id=17)
    coordinator.release_audio.assert_called_once_with("TTS")
    coordinator._resume_trigger_after_tts.assert_called_once_with()
    assert not coordinator._is_speaking.is_set()


def test_denied_audio_never_speaks_or_releases_unowned_audio():
    coordinator = _coordinator()
    coordinator.acquire_audio.side_effect = RuntimeError("owned elsewhere")

    coordinator._speak_with_interrupt_detection("hello")

    coordinator.sink.speak.assert_not_called()
    coordinator.release_audio.assert_not_called()
    coordinator._resume_trigger_after_tts.assert_called_once_with()
    assert not coordinator._is_speaking.is_set()


def test_sink_failure_releases_audio_resumes_input_and_is_contained():
    coordinator = _coordinator()
    coordinator.sink.speak.side_effect = RuntimeError("speaker failed")

    coordinator._speak_with_interrupt_detection("hello")

    coordinator.release_audio.assert_called_once_with("TTS")
    coordinator._resume_trigger_after_tts.assert_called_once_with()
    assert not coordinator._is_speaking.is_set()
    assert any(
        "Fatal error during speech" in call.args[0]
        for call in coordinator.logger.error.call_args_list
    )


def test_pause_failure_does_not_block_owned_speech_or_attempt_resume():
    coordinator = _coordinator()
    coordinator._pause_trigger_for_tts.side_effect = RuntimeError("pause failed")

    coordinator._speak_with_interrupt_detection("hello")

    coordinator.acquire_audio.assert_called_once_with("TTS")
    coordinator.sink.speak.assert_called_once_with("hello", interaction_id=17)
    coordinator.release_audio.assert_called_once_with("TTS")
    coordinator._resume_trigger_after_tts.assert_not_called()
    assert not coordinator._is_speaking.is_set()
