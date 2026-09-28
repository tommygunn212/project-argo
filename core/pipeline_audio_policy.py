"""Audio acceptance policy for the classic STT pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioRejectionThresholds:
    min_duration_s: float
    min_rms: float
    max_silence_ratio: float


def should_reject_audio(
    rms: float,
    silence_ratio: float,
    duration_s: float,
    *,
    thresholds: AudioRejectionThresholds,
    personal_mode: bool,
) -> tuple[bool, str]:
    """Return whether captured audio is too short, quiet, and silent for STT."""

    if personal_mode and duration_s >= 0.2 and rms >= 0.002:
        return False, ""
    if duration_s >= thresholds.min_duration_s or rms >= thresholds.min_rms:
        return False, ""
    if silence_ratio < thresholds.max_silence_ratio:
        return False, ""
    return True, (
        f"VAD discard: rms={rms:.4f}, duration_ms={duration_s * 1000:.0f}, "
        f"silence_ratio={silence_ratio:.2f}"
    )
