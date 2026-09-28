"""Characterization tests for coordinator transition safety."""

from types import SimpleNamespace
from unittest.mock import Mock

from core.coordinator import Coordinator
from core.state_machine import State


def _coordinator(state: State = State.LISTENING) -> Coordinator:
    coordinator = Coordinator.__new__(Coordinator)
    coordinator.state_machine = SimpleNamespace(current_state=state)
    coordinator.on_illegal_transition = None
    coordinator.stop_requested = False
    return coordinator


def test_safe_transition_returns_success_without_reporting(monkeypatch):
    coordinator = _coordinator()
    action = Mock(return_value=True)
    event = Mock()
    monkeypatch.setattr("core.coordinator.log_event", event)

    assert coordinator._safe_transition(
        action, State.THINKING, "test", "turn-1"
    ) is True

    action.assert_called_once_with()
    event.assert_not_called()
    assert coordinator.stop_requested is False


def test_illegal_transition_reports_payload_and_requests_stop(monkeypatch):
    coordinator = _coordinator()
    action = Mock(side_effect=RuntimeError("invalid transition"))
    callback = Mock()
    event = Mock()
    coordinator.on_illegal_transition = callback
    monkeypatch.setattr("core.coordinator.log_event", event)

    assert coordinator._safe_transition(
        action, State.SPEAKING, "wake", "turn-2"
    ) is False

    payload = callback.call_args.args[0]
    assert payload["from"] == "LISTENING"
    assert payload["to"] == "SPEAKING"
    assert set(payload["allowed"]) == {"THINKING"}
    assert payload["source"] == "wake"
    assert payload["interaction_id"] == "turn-2"
    event.assert_called_once_with(
        "ILLEGAL_TRANSITION LISTENING->SPEAKING source=wake",
        stage="state",
        interaction_id="turn-2",
    )
    assert coordinator.stop_requested is True


def test_illegal_transition_callback_failure_is_contained(monkeypatch):
    coordinator = _coordinator(State.THINKING)
    coordinator.on_illegal_transition = Mock(
        side_effect=RuntimeError("dashboard disconnected")
    )
    monkeypatch.setattr("core.coordinator.log_event", Mock())

    assert coordinator._safe_transition(
        Mock(side_effect=RuntimeError("invalid")),
        State.LISTENING,
        "test",
    ) is False

    assert coordinator.stop_requested is True

