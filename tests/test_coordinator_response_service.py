"""Characterization tests for coordinator response helpers and delivery."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.coordinator import Coordinator


def _coordinator():
    coordinator = Coordinator.__new__(Coordinator)
    coordinator.runtime_overrides = {"tts_enabled": True}
    coordinator.interaction_id = 7
    coordinator._response_interaction_id = None
    coordinator._response_committed = False
    coordinator.logger = Mock()
    coordinator.acquire_audio = Mock()
    coordinator.release_audio = Mock()
    coordinator.sink = SimpleNamespace(speak=Mock())
    return coordinator


def test_count_response_is_bounded_and_understands_words():
    coordinator = _coordinator()

    assert coordinator._build_count_response("count to three") == "1, 2, 3"
    assert coordinator._build_count_response("count to 500").endswith("49, 50")


def test_safe_speak_commits_only_one_response_per_interaction():
    coordinator = _coordinator()

    coordinator._safe_speak("first", interaction_id=7)
    coordinator._safe_speak("duplicate", interaction_id=7)

    coordinator.sink.speak.assert_called_once_with("first", interaction_id=7)
    coordinator.acquire_audio.assert_called_once_with("TTS")
    coordinator.release_audio.assert_called_once_with("TTS")
    coordinator.logger.warning.assert_called_once()


def test_safe_speak_resets_guard_for_new_interaction():
    coordinator = _coordinator()

    coordinator._safe_speak("first", interaction_id=7)
    coordinator._safe_speak("second", interaction_id=8)

    assert coordinator.sink.speak.call_count == 2
    assert coordinator._response_interaction_id == 8
    assert coordinator._response_committed is True


def test_safe_speak_releases_audio_when_sink_fails():
    coordinator = _coordinator()
    coordinator.sink.speak.side_effect = RuntimeError("speaker failed")

    with pytest.raises(RuntimeError, match="speaker failed"):
        coordinator._safe_speak("hello", interaction_id=7)

    coordinator.release_audio.assert_called_once_with("TTS")


def test_safe_speak_does_nothing_when_tts_is_disabled():
    coordinator = _coordinator()
    coordinator.runtime_overrides["tts_enabled"] = False

    coordinator._safe_speak("hello", interaction_id=7)

    coordinator.acquire_audio.assert_not_called()
    coordinator.sink.speak.assert_not_called()
