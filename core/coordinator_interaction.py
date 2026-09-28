"""One complete Classic Voice coordinator interaction."""

from __future__ import annotations

import time
from typing import Any, Callable, Protocol

from core.coordinator_generation_stage import generate_interaction_response
from core.coordinator_music_stage import stop_active_music_for_phrase
from core.coordinator_response_guard import CoordinatorResponseGuard
from core.coordinator_response_stage import deliver_and_record_response
from core.coordinator_stages import (
    capture_audio_stage,
    dispatch_procedural_stage,
    dispatch_simple_deterministic_stage,
    parse_intent_stage,
    process_transcript_stage,
    transcribe_audio_stage,
)
from core.coordinator_system_health_stage import dispatch_system_health_stage
from core.latency_probe import LatencyProbe


class CoordinatorInteractionHost(Protocol):
    """Coordinator state used by a single interaction."""

    MAX_INTERACTIONS: int
    audio_owner: Any
    current_probe: Any
    interaction_count: int
    logger: Any
    memory: Any
    next_interaction_overrides: dict[str, Any]
    _is_processing: Any
    _is_speaking: Any
    _last_utterance_time: float | None

    def force_release_audio(self, reason: str) -> None: ...


def run_coordinator_interaction(
    coordinator: CoordinatorInteractionHost,
    *,
    initial_frames: list | None = None,
    mark_wake: bool = False,
    event_logger: Callable[..., None],
) -> bool:
    """Process one interaction and always release its audio authority."""
    is_music_iteration = False
    coordinator.interaction_count += 1
    coordinator.logger.info(f"\n{'=' * 60}")
    coordinator.logger.info(
        f"[Loop] Iteration {coordinator.interaction_count}/{coordinator.MAX_INTERACTIONS}"
    )
    coordinator.logger.info(f"[Loop] Memory: {coordinator.memory}")
    coordinator.logger.info(f"{'=' * 60}")

    overrides = dict(coordinator.next_interaction_overrides)
    if overrides:
        event_logger(f"NEXT_INTERACTION_OVERRIDES_APPLIED {overrides}")
    coordinator.next_interaction_overrides.clear()

    try:
        if coordinator._is_speaking.is_set():
            coordinator.logger.info(
                "[Iteration] Skipping interaction: currently speaking"
            )
            coordinator.interaction_count -= 1
            return False
        coordinator._is_processing.set()
        current_owner = coordinator.audio_owner.get_owner()
        if current_owner and not overrides.get("force_passive_listening"):
            event_logger(f"STT_BLOCKED_AUDIO_OWNER owner={current_owner}")
            coordinator.interaction_count -= 1
            return False

        coordinator.current_probe = LatencyProbe(coordinator.interaction_count)
        if mark_wake:
            coordinator.current_probe.mark("wake_detected")

        audio_bytes = capture_audio_stage(
            coordinator, initial_frames=initial_frames
        )
        text = transcribe_audio_stage(coordinator, audio_bytes)
        transcript_result = process_transcript_stage(coordinator, text, overrides)
        if not transcript_result.continue_processing:
            return transcript_result.interaction_result
        text = transcript_result.text
        parse_result = parse_intent_stage(coordinator, text, event_logger)
        if not parse_result.continue_processing:
            return parse_result.interaction_result
        intent = parse_result.intent
        response_guard = CoordinatorResponseGuard(coordinator)

        deterministic_result = dispatch_simple_deterministic_stage(
            coordinator, intent, text
        )
        if deterministic_result.handled:
            response_guard.set_output(deterministic_result.output_produced)
            response_guard.finalize()
            return deterministic_result.interaction_result
        if dispatch_system_health_stage(
            coordinator,
            intent,
            response_guard.mark_output,
            response_guard.finalize,
        ):
            return True
        procedural_result = dispatch_procedural_stage(
            coordinator,
            text,
            response_guard.mark_output,
            response_guard.finalize,
        )
        if procedural_result.handled:
            response_guard.set_output(procedural_result.output_produced)
            return procedural_result.interaction_result
        if stop_active_music_for_phrase(
            coordinator, text, response_guard.finalize
        ):
            return True

        generation = generate_interaction_response(
            coordinator,
            intent,
            response_guard.mark_output,
            response_guard.finalize,
        )
        response_guard.set_output(generation.output_produced)
        is_music_iteration = generation.is_music_iteration
        if generation.return_interaction:
            return generation.interaction_result
        response_guard.set_output(
            deliver_and_record_response(
                coordinator,
                intent=intent,
                user_text=text,
                response_text=generation.response_text,
                overrides=overrides,
                output_produced=response_guard.output_produced,
            )
        )
        response_guard.finalize()

        if is_music_iteration:
            coordinator.interaction_count -= 1
            coordinator.logger.info(
                "[Iteration] Music iteration complete - decremented counter "
                f"to {coordinator.interaction_count}"
            )
        coordinator._last_utterance_time = time.time()
        return True
    except Exception as error:
        coordinator.logger.error(
            f"[Iteration {coordinator.interaction_count}] Failed: {error}"
        )
        raise
    finally:
        try:
            coordinator.force_release_audio("ITERATION_END")
        except Exception as error:
            coordinator.logger.warning(
                f"[Iteration] Error resetting audio owner: {error}"
            )
        coordinator._is_processing.clear()
