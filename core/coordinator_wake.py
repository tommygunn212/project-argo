"""Wake-event orchestration with explicit coordinator dependencies."""

from dataclasses import dataclass
from typing import Any, Callable

from core.state_machine import State


@dataclass(frozen=True)
class WakeEventDependencies:
    current_state: Callable[[], State]
    is_asleep: Callable[[], bool]
    is_processing: Callable[[], bool]
    is_speaking: Callable[[], bool]
    clear_speaking: Callable[[], None]
    force_release_audio: Callable[[str], None]
    stop_speech: Callable[[], None]
    safe_transition: Callable[..., bool]
    listening_transition: Callable[[], Any]
    wake_transition: Callable[[], Any]
    get_interaction_id: Callable[[], int]
    set_interaction_id: Callable[[int], None]
    set_stop_requested: Callable[[bool], None]
    assert_no_interaction_id_reuse: Callable[[], None]
    set_last_utterance_time: Callable[[float], None]
    play_wake_ack: Callable[[], None]
    handle_interaction: Callable[..., bool]
    event_logger: Callable[[str], None]
    logger: Any
    time_now: Callable[[], float]


def handle_wake_event(dependencies: WakeEventDependencies) -> None:
    """Handle one queued wake event on the coordinator's main thread."""

    state = dependencies.current_state()
    dependencies.event_logger(f"WAKE_WORD detected (state={state.value})")

    if dependencies.is_processing():
        dependencies.logger.info("[Wake] Already processing, ignoring wake event")
        return

    interaction_id = dependencies.get_interaction_id()
    if dependencies.is_speaking():
        dependencies.logger.info("[Wake] BARGE-IN: Wake word detected while speaking")
        dependencies.event_logger("BARGE_IN start")
        try:
            dependencies.force_release_audio("BARGE_IN")
            dependencies.event_logger("AUDIO KILLED")
            dependencies.logger.info("[Wake] Audio authority hard-killed output")
        except Exception as exc:
            dependencies.logger.warning(f"[Wake] Error hard-killing output: {exc}")

        try:
            dependencies.stop_speech()
            dependencies.logger.info("[Wake] TTS stopped synchronously")
        except Exception as exc:
            dependencies.logger.warning(f"[Wake] Error stopping TTS: {exc}")
        dependencies.clear_speaking()

        try:
            dependencies.safe_transition(
                dependencies.listening_transition(),
                State.LISTENING,
                source="audio",
                interaction_id=str(interaction_id),
            )
            dependencies.event_logger("STATE_CHANGE SPEAKING -> LISTENING (barge-in)")
            dependencies.logger.info("[State] SPEAKING -> LISTENING (barge-in)")
        except RuntimeError as exc:
            dependencies.logger.error(
                f"[Wake] FATAL: Invalid state transition: {exc}"
            )
            dependencies.set_stop_requested(True)
            return
        except Exception as exc:
            dependencies.logger.warning(
                f"[Wake] Error setting LISTENING state: {exc}"
            )
    else:
        try:
            if dependencies.is_asleep():
                dependencies.safe_transition(
                    dependencies.wake_transition(),
                    State.LISTENING,
                    source="audio",
                    interaction_id=str(interaction_id),
                )
        except RuntimeError as exc:
            dependencies.logger.error(
                f"[Wake] FATAL: Invalid state transition: {exc}"
            )
            dependencies.set_stop_requested(True)
            return
        except Exception as exc:
            dependencies.logger.warning(f"[Wake] Error waking from sleep: {exc}")
            return

    dependencies.set_interaction_id(interaction_id + 1)
    dependencies.assert_no_interaction_id_reuse()
    dependencies.set_last_utterance_time(dependencies.time_now())
    dependencies.play_wake_ack()
    dependencies.handle_interaction(mark_wake=True)
