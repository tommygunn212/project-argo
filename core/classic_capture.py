"""Finalize and dispatch one captured turn from the classic VAD loop."""

from __future__ import annotations

import threading
from typing import Any, Callable, Protocol, Sequence

import numpy as np


class CaptureAudio(Protocol):
    def clear_buffers(self) -> None: ...


class CapturePipeline(Protocol):
    def run_interaction(self, *args: Any) -> Any: ...

    def transition_state(self, state: str, **kwargs: Any) -> Any: ...


def finish_classic_capture(
    speech_buffer: Sequence[Any],
    *,
    audio: CaptureAudio,
    pipeline: CapturePipeline,
    interaction_id: str,
    voice_mode: str,
    smooth_voice_mode: str,
    next_interaction_overrides: dict[str, Any],
    sound_cues: Any,
    logger: Any,
    event_logger: Callable[..., Any],
    thread_factory: Callable[..., Any] = threading.Thread,
) -> None:
    """Normalize a completed capture, enforce mic ownership, and dispatch it."""
    if not speech_buffer:
        audio.clear_buffers()
        sound_cues.set_capture_active(False)
        sound_cues.play("error", interaction_id=interaction_id)
        pipeline.transition_state("LISTENING", source="empty_reject")
        return

    full_audio = np.concatenate(speech_buffer)
    peak = np.max(np.abs(full_audio))
    if peak <= 0.01:
        logger.warning(f"[Audio] Input too quiet/silent (peak: {peak:.4f}), ignoring")
        audio.clear_buffers()
        sound_cues.play("error", interaction_id=interaction_id)
        pipeline.transition_state("LISTENING", source="quiet_reject")
        return

    if peak < 0.85:
        full_audio = full_audio * (0.9 / peak)
        logger.info(f"[Audio] Normalized input (original peak: {peak:.4f} -> 0.9)")
    else:
        logger.info(f"[Audio] Skipping normalization (peak: {peak:.4f} >= 0.85)")
    full_audio = np.squeeze(full_audio)
    audio.clear_buffers()

    if voice_mode == smooth_voice_mode:
        logger.warning(
            "[VoiceMode] dropped a classic turn: Smooth Voice owns "
            "the microphone (%.1fs of audio discarded)",
            len(full_audio) / 16000.0,
        )
        event_logger(
            "CLASSIC_TURN_DROPPED reason=smooth_voice_owns_mic",
            stage="voice_mode",
            interaction_id=interaction_id,
        )
        audio.clear_buffers()
        pipeline.transition_state("LISTENING", source="smooth_owns_mic")
        return

    overrides = dict(next_interaction_overrides)
    next_interaction_overrides.clear()
    worker = thread_factory(
        target=pipeline.run_interaction,
        args=(full_audio, interaction_id, False, overrides),
    )
    worker.start()
