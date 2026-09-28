"""Characterization tests for wrapper state-transition compatibility helpers."""

from types import SimpleNamespace
from unittest.mock import Mock

from wrapper import argo


def test_thinking_transition_requires_available_state_machine(monkeypatch):
    state_machine = SimpleNamespace(accept_command=Mock(return_value=True))
    monkeypatch.setattr(argo, "_state_machine", state_machine)
    monkeypatch.setattr(argo, "STATE_MACHINE_AVAILABLE", False)

    assert argo._transition_to_thinking() is False
    state_machine.accept_command.assert_not_called()


def test_thinking_transition_returns_state_machine_result(monkeypatch):
    state_machine = SimpleNamespace(accept_command=Mock(return_value=True))
    monkeypatch.setattr(argo, "_state_machine", state_machine)
    monkeypatch.setattr(argo, "STATE_MACHINE_AVAILABLE", True)

    assert argo._transition_to_thinking() is True
    state_machine.accept_command.assert_called_once_with()


def test_speaking_transition_requires_available_state_machine(monkeypatch):
    state_machine = SimpleNamespace(start_audio=Mock(return_value=True))
    monkeypatch.setattr(argo, "_state_machine", state_machine)
    monkeypatch.setattr(argo, "STATE_MACHINE_AVAILABLE", False)

    assert argo._transition_to_speaking() is False
    state_machine.start_audio.assert_not_called()


def test_speaking_transition_preserves_rejected_transition(monkeypatch):
    state_machine = SimpleNamespace(start_audio=Mock(return_value=False))
    monkeypatch.setattr(argo, "_state_machine", state_machine)
    monkeypatch.setattr(argo, "STATE_MACHINE_AVAILABLE", True)

    assert argo._transition_to_speaking() is False
    state_machine.start_audio.assert_called_once_with()

