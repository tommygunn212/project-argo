"""Failure-isolated hard reset for the classic pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class PipelineResetDependencies:
    set_stop_signal: Callable[[], None]
    stop_tts: Callable[[], None]
    stop_music: Callable[[], None]
    force_release_audio: Callable[[str], None]
    stop_playback: Callable[[], None]
    clear_buffers: Callable[[], None]
    clear_speaking_flags: Callable[[], None]
    processing_lock_is_held: Callable[[], bool]
    release_processing_lock: Callable[[], None]
    force_idle: Callable[[], None]
    logger: Any
    record_event: Callable[..., Any]


def hard_reset_pipeline(
    dependencies: PipelineResetDependencies,
    reason: str,
) -> dict[str, Any]:
    """Attempt every recovery step and report failures without aborting cleanup."""
    actions: list[str] = []
    failures: list[str] = []

    def attempt(label: str, action: Callable[[], None]) -> None:
        try:
            action()
            actions.append(label)
        except Exception as exc:
            failures.append(f"{label}: {type(exc).__name__}")

    attempt("stop_signal", dependencies.set_stop_signal)
    attempt("tts_stopped", dependencies.stop_tts)
    attempt("music_stopped", dependencies.stop_music)
    attempt(
        "audio_released", lambda: dependencies.force_release_audio(reason)
    )
    attempt("playback_stopped", dependencies.stop_playback)
    attempt("buffers_cleared", dependencies.clear_buffers)
    attempt("flags_cleared", dependencies.clear_speaking_flags)

    lock_broken = False
    if dependencies.processing_lock_is_held():
        try:
            dependencies.release_processing_lock()
            lock_broken = True
            actions.append("processing_lock_broken")
        except RuntimeError:
            failures.append("processing_lock: not held by this thread")

    attempt("state_idle", dependencies.force_idle)
    dependencies.logger.warning(
        "[HARD_RESET] reason=%s actions=%s failures=%s",
        reason,
        actions,
        failures,
    )
    dependencies.record_event(
        f"HARD_RESET reason={reason} lock_broken={lock_broken}",
        stage="control",
    )
    return {
        "ok": True,
        "reason": reason,
        "actions": actions,
        "failures": failures,
        "processing_lock_broken": lock_broken,
    }
