import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.coordinator_interaction import run_coordinator_interaction


def _host(*, speaking=False, owner=None):
    speaking_event = threading.Event()
    if speaking:
        speaking_event.set()
    return SimpleNamespace(
        MAX_INTERACTIONS=10,
        audio_owner=SimpleNamespace(get_owner=lambda: owner),
        current_probe=None,
        interaction_count=2,
        logger=Mock(),
        memory="memory",
        next_interaction_overrides={},
        _is_processing=threading.Event(),
        _is_speaking=speaking_event,
        _last_utterance_time=None,
        force_release_audio=Mock(),
    )


def test_speaking_turn_is_skipped_without_consuming_interaction():
    coordinator = _host(speaking=True)

    result = run_coordinator_interaction(coordinator, event_logger=Mock())

    assert result is False
    assert coordinator.interaction_count == 2
    coordinator.force_release_audio.assert_called_once_with("ITERATION_END")
    assert not coordinator._is_processing.is_set()


def test_audio_owner_blocks_stt_and_is_reported():
    coordinator = _host(owner="TTS")
    events = Mock()

    result = run_coordinator_interaction(coordinator, event_logger=events)

    assert result is False
    assert coordinator.interaction_count == 2
    events.assert_called_once_with("STT_BLOCKED_AUDIO_OWNER owner=TTS")
    coordinator.force_release_audio.assert_called_once_with("ITERATION_END")
    assert not coordinator._is_processing.is_set()


def test_capture_failure_still_releases_audio_and_processing(monkeypatch):
    coordinator = _host()
    monkeypatch.setattr(
        "core.coordinator_interaction.capture_audio_stage",
        Mock(side_effect=RuntimeError("capture failed")),
    )

    with pytest.raises(RuntimeError, match="capture failed"):
        run_coordinator_interaction(coordinator, event_logger=Mock())

    coordinator.force_release_audio.assert_called_once_with("ITERATION_END")
    assert not coordinator._is_processing.is_set()
