"""State-machine transitions used by the classic wrapper facade."""

from __future__ import annotations

from typing import Any, Callable


def transition_to_thinking(
    state_machine_available: bool,
    state_machine: Any,
    status_sink: Callable[[str], None],
) -> bool:
    if not state_machine_available or state_machine is None:
        return False
    if not state_machine.accept_command():
        return False
    status_sink("[STATE] Accepted command (LISTENING -> THINKING)")
    return True


def transition_to_speaking(
    state_machine_available: bool,
    state_machine: Any,
    status_sink: Callable[[str], None],
) -> bool:
    if not state_machine_available or state_machine is None:
        return False
    if not state_machine.start_audio():
        return False
    status_sink("[STATE] Starting audio (THINKING -> SPEAKING)")
    return True
