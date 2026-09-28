"""Ambient-noise calibration for classic voice activity detection."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable, Protocol

import numpy as np


class CalibrationAudio(Protocol):
    running: bool

    def read_frame(self, timeout: float | None = None): ...


@dataclass(frozen=True)
class NoiseCalibrationResult:
    vad_threshold: float
    barge_in_threshold: float
    calibrated: bool


def calibrate_ambient_noise(
    audio: CalibrationAudio,
    *,
    server_enabled: bool,
    current_vad_threshold: float,
    current_barge_in_threshold: float,
    config_vad_threshold: float,
    calibration_max_multiple: float,
    input_sample_rate: int,
    block_size: int,
    broadcast: Callable[[str, Any], None],
    logger: logging.Logger,
    duration_seconds: float = 2.0,
    multiplier: float = 2.5,
) -> NoiseCalibrationResult:
    """Measure ambient input and calculate bounded VAD thresholds."""
    if not server_enabled or not getattr(audio, "running", False):
        logger.warning("[CALIBRATE] Audio is stopped; start listening before calibration")
        broadcast("log", "Calibration skipped — start listening first")
        return NoiseCalibrationResult(
            current_vad_threshold,
            current_barge_in_threshold,
            False,
        )

    frames_needed = int((input_sample_rate / block_size) * duration_seconds)
    rms_samples = []
    broadcast(
        "log",
        f"Calibrating ambient noise ({duration_seconds}s) — stay quiet...",
    )
    logger.info(
        f"[CALIBRATE] Recording {duration_seconds}s of ambient noise "
        f"({frames_needed} frames)..."
    )
    for _ in range(frames_needed):
        frame = audio.read_frame(timeout=0.05)
        if frame is not None:
            rms_samples.append(np.linalg.norm(frame) * 10)

    if not rms_samples:
        logger.warning("[CALIBRATE] No frames captured, keeping config threshold")
        broadcast("log", "Calibration failed — no audio frames")
        return NoiseCalibrationResult(
            config_vad_threshold,
            current_barge_in_threshold,
            False,
        )

    noise_floor = np.mean(rms_samples)
    noise_peak = np.percentile(rms_samples, 95)
    adaptive_threshold = max(noise_peak * 1.5, noise_floor * multiplier)
    adaptive_threshold = max(adaptive_threshold, config_vad_threshold)
    ceiling = config_vad_threshold * calibration_max_multiple
    if adaptive_threshold > ceiling:
        logger.warning(
            "[CALIBRATE] Measured floor implies a threshold of %.3f, above the "
            "ceiling of %.3f (%.1fx the configured %.3f). Something was probably "
            "making noise. Clamping - recalibrate in a quiet room.",
            adaptive_threshold,
            ceiling,
            calibration_max_multiple,
            config_vad_threshold,
        )
        broadcast(
            "log",
            "Calibration heard too much noise - threshold clamped. "
            "Recalibrate in a quiet room.",
        )
        adaptive_threshold = ceiling

    vad_threshold = float(adaptive_threshold)
    barge_in_threshold = vad_threshold * 1.2
    logger.info(
        f"[CALIBRATE] Noise floor: mean={noise_floor:.3f} p95={noise_peak:.3f} "
        f"-> VAD threshold: {vad_threshold:.3f}, "
        f"barge-in: {barge_in_threshold:.3f}"
    )
    broadcast(
        "log",
        f"Noise calibrated — floor: {noise_floor:.2f}, "
        f"VAD threshold: {vad_threshold:.2f}",
    )
    broadcast(
        "noise_calibration",
        {
            "noise_floor": round(float(noise_floor), 3),
            "noise_peak_p95": round(float(noise_peak), 3),
            "vad_threshold": round(vad_threshold, 3),
            "barge_in_threshold": round(barge_in_threshold, 3),
        },
    )
    return NoiseCalibrationResult(vad_threshold, barge_in_threshold, True)
