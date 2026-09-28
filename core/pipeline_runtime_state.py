"""State transitions and synchronous interruption for the classic pipeline."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class PipelineRuntimeStateDependencies:
    state_lock: threading.Lock
    get_state: Callable[[], str]
    set_state: Callable[[str], None]
    allowed_transitions: Callable[[str], set[str]]
    stop_requested: Callable[[], bool]
    set_stop_signal: Callable[[], None]
    get_is_speaking: Callable[[], bool]
    set_is_speaking: Callable[[bool], None]
    set_tts_finished_at: Callable[[float], None]
    current_interaction_id: Callable[[], str]
    append_timeline: Callable[[dict[str, Any]], None]
    clear_illegal_transition: Callable[[], None]
    mark_illegal_transition: Callable[[dict[str, Any]], None]
    broadcast: Callable[[str, Any], None]
    play_sound_cue: Callable[..., None]
    stop_active_cue: Callable[[str, str], None]
    stop_tts: Callable[[], None]
    force_release_audio: Callable[[str, str], None]
    stop_playback: Callable[[], None]
    clear_buffers: Callable[[], None]
    force_pipeline_state: Callable[..., None]
    record_event: Callable[..., None]
    monotonic: Callable[[], float] = time.monotonic
    wall_time: Callable[[], float] = time.time


class PipelineRuntimeStateService:
    """Own classic state transitions without depending on the pipeline object."""

    def __init__(self, dependencies: PipelineRuntimeStateDependencies):
        self._dependencies = dependencies

    def record_timeline(
        self, event: str, stage: str, interaction_id: str = ""
    ) -> None:
        dependencies = self._dependencies
        dependencies.append_timeline(
            {
                "t": int(dependencies.monotonic() * 1000),
                "id": interaction_id,
                "stage": stage,
                "event": event,
            }
        )
        dependencies.record_event(
            event, stage=stage, interaction_id=interaction_id
        )

    def transition_state(
        self,
        new_state: str,
        interaction_id: str = "",
        source: str = "audio",
    ) -> bool:
        dependencies = self._dependencies
        with dependencies.state_lock:
            old_state = dependencies.get_state()
            if (
                old_state == "IDLE"
                and new_state == "LISTENING"
                and source == "audio"
                and dependencies.stop_requested()
            ):
                self.record_timeline(
                    "STATE IDLE->LISTENING ignored after interrupt",
                    stage="state",
                    interaction_id=interaction_id,
                )
                return True
            if new_state == old_state:
                return True
            allowed_states = dependencies.allowed_transitions(old_state)
            if new_state not in allowed_states:
                payload = {
                    "from": old_state,
                    "to": new_state,
                    "allowed": list(allowed_states),
                    "source": source,
                    "interaction_id": interaction_id,
                }
                dependencies.mark_illegal_transition(payload)
                self.record_timeline(
                    f"ILLEGAL_TRANSITION {old_state}->{new_state} source={source}",
                    stage="state",
                    interaction_id=interaction_id,
                )
                dependencies.broadcast("illegal_transition", payload)
                dependencies.broadcast("status", "ERROR")
                dependencies.broadcast(
                    "log", f"ILLEGAL TRANSITION: {old_state} → {new_state}"
                )
                dependencies.play_sound_cue(
                    "error", interaction_id=interaction_id
                )
                if dependencies.get_is_speaking():
                    try:
                        dependencies.set_stop_signal()
                        dependencies.stop_tts()
                        dependencies.force_release_audio(
                            "ILLEGAL_TRANSITION", interaction_id
                        )
                        dependencies.stop_playback()
                    except Exception:
                        pass
                return False
            dependencies.set_state(new_state)
            self.record_timeline(
                f"STATE {old_state}->{new_state}",
                stage="state",
                interaction_id=interaction_id,
            )
            dependencies.broadcast("status", new_state)
            self.play_state_sound_cue(old_state, new_state, interaction_id)
            return True

    def force_state(
        self,
        new_state: str,
        interaction_id: str = "",
        source: str = "BARGE_IN",
    ) -> None:
        dependencies = self._dependencies
        with dependencies.state_lock:
            old_state = dependencies.get_state()
            dependencies.set_state(new_state)
            self.record_timeline(
                f"STATE {old_state}->{new_state} (forced, source={source})",
                stage="state",
                interaction_id=interaction_id,
            )
            dependencies.broadcast("status", new_state)

    def play_state_sound_cue(
        self, old_state: str, new_state: str, interaction_id: str = ""
    ) -> None:
        play = self._dependencies.play_sound_cue
        if new_state == "THINKING":
            play("thinking_start", interaction_id=interaction_id)
        elif new_state == "SPEAKING":
            play("speaking_start", interaction_id=interaction_id, block=True)
        elif new_state == "LISTENING":
            if old_state == "SPEAKING":
                play("speaking_end", interaction_id=interaction_id)
            else:
                play("listening_start", interaction_id=interaction_id)

    def reset_interaction(self) -> None:
        self.interrupt_current_response(
            "RESET_INTERACTION", target_state="LISTENING"
        )
        self._dependencies.clear_illegal_transition()

    def interrupt_current_response(
        self,
        reason: str = "INTERRUPT",
        interaction_id: str = "",
        target_state: str | None = "LISTENING",
        clear_buffers: bool = True,
    ) -> None:
        dependencies = self._dependencies
        interaction_id = interaction_id or dependencies.current_interaction_id()
        self.record_timeline(
            f"INTERRUPT {reason}",
            stage="interrupt",
            interaction_id=interaction_id,
        )
        try:
            dependencies.stop_active_cue(reason, interaction_id)
        except Exception:
            pass
        dependencies.set_stop_signal()
        dependencies.stop_tts()
        try:
            dependencies.force_release_audio(reason, interaction_id)
        except Exception:
            pass
        try:
            dependencies.stop_playback()
        except Exception:
            pass
        if clear_buffers:
            try:
                dependencies.clear_buffers()
            except Exception:
                pass
        dependencies.set_is_speaking(False)
        dependencies.set_tts_finished_at(dependencies.wall_time())
        if target_state:
            try:
                dependencies.force_pipeline_state(
                    target_state,
                    interaction_id=interaction_id,
                    source=reason,
                )
            except Exception:
                pass
