"""Input-trigger alignment checks for coordinator state transitions."""

from typing import Any

from core.state_machine import State


def assert_trigger_state(trigger: Any, state: State, logger: Any) -> None:
    """Raise when trigger activity disagrees with the state-machine contract."""

    if not hasattr(trigger, "is_active") or not hasattr(trigger, "is_paused"):
        logger.debug("[Assert] Trigger doesn't support state checks, skipping")
        return

    try:
        if state == State.LISTENING:
            assert trigger.is_active(), (
                f"LISTENING but trigger.is_active()={trigger.is_active()} "
                "(expected True)"
            )
            logger.debug("[Assert] LISTENING: trigger is ACTIVE ✓")
        else:
            assert trigger.is_paused(), (
                f"{state.value} but trigger.is_paused()={trigger.is_paused()} "
                "(expected True)"
            )
            logger.debug(f"[Assert] {state.value}: trigger is PAUSED ✓")
    except AssertionError as exc:
        logger.error(f"[Assert] FATAL: Trigger state contract violated: {exc}")
        raise
