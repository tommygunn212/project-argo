"""Shared dashboard interruption path for classic response playback."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class FrontendInterruptDependencies:
    get_pipeline: Callable[[], Any]
    get_audio: Callable[[], Any]
    stop_active_cue: Callable[..., None]
    logger: Any


def interrupt_current_response(
    dependencies: FrontendInterruptDependencies,
    reason: str,
    *,
    target_state: str = "LISTENING",
    clear_buffers: bool = True,
) -> None:
    """Delegate to the modern pipeline or contain cleanup through legacy fallbacks."""

    pipeline = dependencies.get_pipeline()
    audio = dependencies.get_audio()
    interaction_id = getattr(pipeline, "current_interaction_id", "") if pipeline else ""
    try:
        dependencies.stop_active_cue(reason, interaction_id=interaction_id)
    except Exception:
        pass

    if pipeline and hasattr(pipeline, "interrupt_current_response"):
        try:
            pipeline.interrupt_current_response(
                reason=reason,
                interaction_id=interaction_id,
                target_state=target_state,
                clear_buffers=clear_buffers,
            )
            return
        except Exception as exc:
            dependencies.logger.warning(
                f"[INTERRUPT] Pipeline interrupt failed: {exc}"
            )

    if pipeline:
        try:
            pipeline.stop_signal.set()
            pipeline.stop_tts()
            pipeline.is_speaking = False
        except Exception:
            pass
    if audio:
        try:
            audio.force_release_audio(reason, interaction_id=interaction_id)
            audio.stop_playback()
            if clear_buffers:
                audio.clear_buffers()
        except Exception:
            pass
