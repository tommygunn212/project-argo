"""Bounded top-level run loop for the classic coordinator."""

from __future__ import annotations

import queue
import time
from typing import Any, Protocol

from core.state_machine import State


class CoordinatorLoopHost(Protocol):
    logger: Any
    MAX_INTERACTIONS: int
    STOP_KEYWORDS: Any
    SPEECH_START_POLL_SECONDS: float
    idle_sleep_seconds: float
    memory: Any
    latency_stats: Any
    state_machine: Any
    stop_requested: bool
    interaction_count: int
    interaction_id: Any
    _wake_event_queue: Any
    _last_utterance_time: float | None
    _is_speaking: Any
    _is_processing: Any

    def _start_wake_listener(self) -> None: ...
    def _handle_wake_event(self) -> None: ...
    def _safe_transition(self, action, next_state, source: str, interaction_id: str = "") -> bool: ...
    def _wait_for_speech_start(self, max_wait_seconds: float): ...
    def _handle_interaction(self, initial_frames=None, mark_wake: bool = False) -> bool: ...


def run_coordinator_loop(coordinator: CoordinatorLoopHost) -> None:
    logger = coordinator.logger
    logger.info("[run] Starting Coordinator v4 (interaction loop + session memory)...")
    logger.info(f"[run] Max interactions: {coordinator.MAX_INTERACTIONS}")
    logger.info(f"[run] Stop keywords: {coordinator.STOP_KEYWORDS}")
    logger.info(f"[run] SessionMemory capacity: {coordinator.memory.capacity}")
    coordinator._start_wake_listener()
    try:
        while not coordinator.stop_requested:
            try:
                coordinator._wake_event_queue.get_nowait()
            except queue.Empty:
                pass
            else:
                coordinator._handle_wake_event()
                if coordinator.stop_requested:
                    break
                continue

            if coordinator.state_machine.is_asleep:
                logger.info("[Loop] Sleeping - waiting for wake event...")
                time.sleep(0.05)
                continue

            if coordinator._last_utterance_time is not None:
                idle_elapsed = time.time() - coordinator._last_utterance_time
                if idle_elapsed >= coordinator.idle_sleep_seconds:
                    logger.info(
                        f"[Idle] No activity for {idle_elapsed:.1f}s; entering sleep"
                    )
                    coordinator._safe_transition(
                        coordinator.state_machine.sleep,
                        State.SLEEP,
                        source="ui",
                        interaction_id=str(coordinator.interaction_id),
                    )
                    continue

            if coordinator._is_speaking.is_set() or coordinator._is_processing.is_set():
                time.sleep(0.05)
                continue

            preroll_frames = coordinator._wait_for_speech_start(
                coordinator.SPEECH_START_POLL_SECONDS
            )
            if preroll_frames is None:
                continue
            if not coordinator._handle_interaction(initial_frames=preroll_frames):
                continue
            if coordinator.stop_requested:
                logger.info("[Loop] Stop requested by user")
                break
            if coordinator.interaction_count >= coordinator.MAX_INTERACTIONS:
                try:
                    if _music_is_playing():
                        logger.info(
                            "[Loop] Max interactions reached, but music is playing - continuing loop"
                        )
                        logger.info("[Loop] Waiting for next command or music to finish...")
                    else:
                        logger.info(
                            f"[Loop] Max interactions ({coordinator.MAX_INTERACTIONS}) reached"
                        )
                        break
                except Exception as exc:
                    logger.warning(f"[Loop] Could not check music status: {exc} - exiting")
                    break
            else:
                remaining = coordinator.MAX_INTERACTIONS - coordinator.interaction_count
                logger.info(f"[Loop] Continuing... ({remaining} interactions remaining)")

        logger.info(f"\n{'=' * 60}")
        logger.info(f"[Loop] Exiting after {coordinator.interaction_count} interaction(s)")
        reason = "User requested stop" if coordinator.stop_requested else "Max interactions reached"
        logger.info(f"[Loop] Reason: {reason}")
        logger.info("[Loop] Clearing SessionMemory...")
        coordinator.memory.clear()
        logger.info(f"[Loop] SessionMemory cleared: {coordinator.memory}")
        logger.info(f"{'=' * 60}")
        coordinator.latency_stats.log_report()
        logger.info(f"{'=' * 60}\n")
        logger.info("[run] Coordinator v4 complete")
    except Exception as exc:
        logger.error(f"[run] Failed: {exc}")
        coordinator.memory.clear()
        raise


def _music_is_playing() -> bool:
    from core.music_player import get_music_player

    return bool(get_music_player().is_playing)
