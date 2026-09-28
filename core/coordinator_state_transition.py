"""Failure reporting for coordinator state-machine transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CoordinatorTransitionDependencies:
    current_state: Callable[[], Any]
    allowed_transitions: Callable[[str], set[str]]
    get_illegal_transition_callback: Callable[[], Callable[[dict], None] | None]
    request_stop: Callable[[], None]
    event_logger: Callable[..., None]


def run_safe_transition(
    dependencies: CoordinatorTransitionDependencies,
    action: Callable[[], bool],
    next_state: Any,
    source: str,
    interaction_id: str = "",
) -> bool:
    """Run one transition or report the rejected edge and stop the loop."""
    previous_state = dependencies.current_state()
    try:
        return action()
    except RuntimeError:
        payload = {
            "from": previous_state.value,
            "to": next_state.value,
            "allowed": list(
                dependencies.allowed_transitions(previous_state.value)
            ),
            "source": source,
            "interaction_id": interaction_id,
        }
        dependencies.event_logger(
            f"ILLEGAL_TRANSITION {previous_state.value}->{next_state.value} "
            f"source={source}",
            stage="state",
            interaction_id=interaction_id,
        )
        callback = dependencies.get_illegal_transition_callback()
        if callback:
            try:
                callback(payload)
            except Exception:
                pass
        dependencies.request_stop()
        return False
