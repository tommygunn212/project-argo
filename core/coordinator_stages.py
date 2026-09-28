"""Explicit interaction stages used by :mod:`core.coordinator`."""

from __future__ import annotations

from datetime import datetime
import io
from typing import Any, Optional


def capture_audio_stage(
    coordinator: Any,
    initial_frames: Optional[list] = None,
) -> bytes:
    """Record one utterance and return a WAV payload for STT."""
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] "
        f"Recording (max {coordinator.MAX_RECORDING_DURATION}s, stops on "
        f"{coordinator.SILENCE_DURATION}s silence)..."
    )
    coordinator.current_probe.mark("recording_start")

    if coordinator.on_recording_start:
        try:
            coordinator.on_recording_start()
        except Exception as exc:
            coordinator.logger.debug(
                f"[Coordinator] on_recording_start callback error: {exc}"
            )

    audio = coordinator._record_with_silence_detection(
        initial_frames=initial_frames
    )
    coordinator.current_probe.mark("recording_end")

    if coordinator.on_recording_stop:
        try:
            coordinator.on_recording_stop()
        except Exception as exc:
            coordinator.logger.debug(
                f"[Coordinator] on_recording_stop callback error: {exc}"
            )

    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Recorded {len(audio)} "
        f"samples ({len(audio) / coordinator.AUDIO_SAMPLE_RATE:.2f}s)"
    )

    from scipy.io import wavfile

    audio_buffer = io.BytesIO()
    wavfile.write(audio_buffer, coordinator.AUDIO_SAMPLE_RATE, audio)
    audio_bytes = audio_buffer.getvalue()
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Audio buffer: "
        f"{len(audio_bytes)} bytes"
    )
    return audio_bytes


def transcribe_audio_stage(coordinator: Any, audio_bytes: bytes) -> str:
    """Transcribe one WAV payload and update observer/timing state."""
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Transcribing audio..."
    )
    coordinator.current_probe.mark("stt_start")
    text = coordinator.stt.transcribe(
        audio_bytes, coordinator.AUDIO_SAMPLE_RATE
    )
    coordinator.logger.info(f"[STT RAW] '{text}'")
    coordinator.current_probe.mark("stt_end")

    coordinator._last_wake_timestamp = datetime.now()
    coordinator._last_transcript = text
    coordinator.dynamic_silence_timeout = coordinator.get_dynamic_timeout(text)
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Transcribed: '{text}'"
    )
    return text
