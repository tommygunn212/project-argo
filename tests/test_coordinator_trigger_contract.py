"""Contract tests for coordinator trigger/state alignment."""

from unittest.mock import Mock

import pytest

from core.coordinator import Coordinator
from core.state_machine import State


def _coordinator(trigger):
    coordinator = Coordinator.__new__(Coordinator)
    coordinator.trigger = trigger
    coordinator.logger = Mock()
    return coordinator


def test_trigger_without_state_introspection_is_skipped():
    coordinator = _coordinator(object())

    coordinator._assert_trigger_state(State.LISTENING)

    coordinator.logger.debug.assert_called_once_with(
        "[Assert] Trigger doesn't support state checks, skipping"
    )


def test_listening_requires_active_trigger():
    trigger = Mock()
    trigger.is_active.return_value = True
    coordinator = _coordinator(trigger)

    coordinator._assert_trigger_state(State.LISTENING)

    trigger.is_active.assert_called_once_with()
    trigger.is_paused.assert_not_called()


def test_non_listening_state_requires_paused_trigger():
    trigger = Mock()
    trigger.is_paused.return_value = True
    coordinator = _coordinator(trigger)

    coordinator._assert_trigger_state(State.SPEAKING)

    trigger.is_paused.assert_called_once_with()
    trigger.is_active.assert_not_called()


@pytest.mark.parametrize(
    ("state", "method", "message"),
    [
        (State.LISTENING, "is_active", "LISTENING but trigger.is_active()=False"),
        (State.THINKING, "is_paused", "THINKING but trigger.is_paused()=False"),
    ],
)
def test_trigger_contract_violation_is_fatal_and_logged(state, method, message):
    trigger = Mock()
    getattr(trigger, method).return_value = False
    coordinator = _coordinator(trigger)

    with pytest.raises(AssertionError, match="expected True"):
        coordinator._assert_trigger_state(state)

    assert any(
        message in call.args[0] for call in coordinator.logger.error.call_args_list
    )
