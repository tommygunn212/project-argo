"""Behavior tests for coordinator wake-event orchestration."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

from core.coordinator import Coordinator
from core.state_machine import State


def _coordinator(*, state=State.LISTENING, processing=False, speaking=False):
    coordinator = Coordinator.__new__(Coordinator)
    coordinator.state_machine = SimpleNamespace(
        current_state=state,
        is_asleep=state == State.SLEEP,
        listening=Mock(),
        wake=Mock(),
    )
    coordinator._is_processing = threading.Event()
    coordinator._is_speaking = threading.Event()
    if processing:
        coordinator._is_processing.set()
    if speaking:
        coordinator._is_speaking.set()
    coordinator.logger = Mock()
    coordinator.force_release_audio = Mock()
    coordinator.sink = SimpleNamespace(stop_interrupt=Mock())
    coordinator._safe_transition = Mock()
    coordinator.interaction_id = 7
    coordinator.stop_requested = False
    coordinator._assert_no_interaction_id_reuse = Mock()
    coordinator._last_utterance_time = 0.0
    coordinator._play_wake_ack = Mock()
    coordinator._handle_interaction = Mock()
    return coordinator


def test_processing_coordinator_ignores_wake_without_side_effects(monkeypatch):
    coordinator = _coordinator(processing=True)
    events = []
    monkeypatch.setattr("core.coordinator.log_event", events.append)

    coordinator._handle_wake_event()

    assert events == ["WAKE_WORD detected (state=LISTENING)"]
    coordinator._safe_transition.assert_not_called()
    coordinator._handle_interaction.assert_not_called()
    assert coordinator.interaction_id == 7


def test_speaking_wake_hard_stops_audio_and_returns_to_listening(monkeypatch):
    coordinator = _coordinator(state=State.SPEAKING, speaking=True)
    events = []
    monkeypatch.setattr("core.coordinator.log_event", events.append)

    coordinator._handle_wake_event()

    coordinator.force_release_audio.assert_called_once_with("BARGE_IN")
    coordinator.sink.stop_interrupt.assert_called_once_with()
    assert not coordinator._is_speaking.is_set()
    coordinator._safe_transition.assert_called_once_with(
        coordinator.state_machine.listening,
        State.LISTENING,
        source="audio",
        interaction_id="7",
    )
    assert coordinator.interaction_id == 8
    coordinator._assert_no_interaction_id_reuse.assert_called_once_with()
    coordinator._play_wake_ack.assert_called_once_with()
    coordinator._handle_interaction.assert_called_once_with(mark_wake=True)
    assert "BARGE_IN start" in events
    assert "AUDIO KILLED" in events


def test_fatal_barge_transition_stops_coordinator(monkeypatch):
    coordinator = _coordinator(state=State.SPEAKING, speaking=True)
    coordinator._safe_transition.side_effect = RuntimeError("illegal")
    monkeypatch.setattr("core.coordinator.log_event", lambda _event: None)

    coordinator._handle_wake_event()

    assert coordinator.stop_requested is True
    coordinator._handle_interaction.assert_not_called()
    assert coordinator.interaction_id == 7


def test_sleeping_wake_transitions_then_starts_new_interaction(monkeypatch):
    coordinator = _coordinator(state=State.SLEEP)
    monkeypatch.setattr("core.coordinator.log_event", lambda _event: None)

    coordinator._handle_wake_event()

    coordinator._safe_transition.assert_called_once_with(
        coordinator.state_machine.wake,
        State.LISTENING,
        source="audio",
        interaction_id="7",
    )
    assert coordinator.interaction_id == 8
    coordinator._handle_interaction.assert_called_once_with(mark_wake=True)
