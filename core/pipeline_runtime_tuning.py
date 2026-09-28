"""Validated live tuning overrides for the classic pipeline."""

from __future__ import annotations

from dataclasses import dataclass


def clamped_runtime_float(
    overrides: dict,
    key: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    """Read one numeric override, preserving and clamping its current value."""
    try:
        value = float(overrides.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class PipelineRuntimeTuning:
    stt_min_rms_threshold: float
    stt_silence_ratio_threshold: float
    stt_min_duration_seconds: float
    vad_silence_pad_ms: int
    tts_min_confidence: float
    personal_mode_min_confidence: float


def resolve_runtime_tuning(
    overrides: dict,
    current: PipelineRuntimeTuning,
) -> PipelineRuntimeTuning:
    """Resolve all supported live overrides without mutating the pipeline."""
    def read(key: str, default: float, minimum: float, maximum: float) -> float:
        return clamped_runtime_float(
            overrides, key, default, minimum, maximum
        )
    return PipelineRuntimeTuning(
        stt_min_rms_threshold=read(
            "stt_min_rms_threshold", current.stt_min_rms_threshold, 0.0, 0.2
        ),
        stt_silence_ratio_threshold=read(
            "stt_silence_ratio_threshold",
            current.stt_silence_ratio_threshold,
            0.0,
            1.0,
        ),
        stt_min_duration_seconds=read(
            "stt_min_duration_s", current.stt_min_duration_seconds, 0.05, 5.0
        ),
        vad_silence_pad_ms=int(
            read(
                "vad_silence_pad_ms",
                float(current.vad_silence_pad_ms),
                0.0,
                3000.0,
            )
        ),
        tts_min_confidence=read(
            "tts_min_confidence", current.tts_min_confidence, 0.0, 1.0
        ),
        personal_mode_min_confidence=read(
            "personal_mode_min_confidence",
            current.personal_mode_min_confidence,
            0.0,
            1.0,
        ),
    )
