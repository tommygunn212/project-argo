"""VAD calibration and capture dispatch for the classic backend runtime."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class ClassicMainRuntime:
    audio: Any
    pipeline: Any
    config: Any
    environment: Mapping[str, str]
    get_server_enabled: Callable[[], bool]
    get_listening_enabled: Callable[[], bool]
    disable_listening: Callable[[], None]
    get_voice_mode: Callable[[], str]
    smooth_voice_mode: str
    runtime_overrides: dict[str, Any]
    input_sample_rate: int
    block_size: int
    broadcast: Callable[[str, Any], None]
    logger: Any
    calibrate_ambient_noise: Callable[..., Any]
    set_noise_calibrator: Callable[[Callable[..., float]], None]
    run_capture_loop: Callable[..., None]
    interrupt_current_response: Callable[..., Any]
    next_interaction_overrides: dict[str, Any]
    sound_cues: Any
    event_logger: Callable[..., Any]


def run_classic_main_runtime(runtime: ClassicMainRuntime) -> None:
    """Calibrate thresholds, select initial state, and run classic capture."""
    config_vad_threshold = float(
        runtime.config.get(
            "audio.vad_threshold",
            runtime.environment.get("ARGO_VAD_THRESHOLD", "5.0"),
        )
    )
    # Hard ceiling on what calibration may raise the threshold to. Without it,
    # one noisy calibration window can make ARGO deaf until restart.
    calibration_max_multiple = float(
        runtime.config.get(
            "audio.calibration_max_multiple",
            runtime.environment.get("ARGO_CALIBRATION_MAX_MULTIPLE", "3.0"),
        )
    )
    barge_in_threshold = float(
        runtime.config.get(
            "audio.barge_in_threshold",
            runtime.environment.get("ARGO_BARGE_IN_THRESHOLD", "6.0"),
        )
    )
    vad_threshold = config_vad_threshold

    def calibrate_noise_floor(
        duration_sec: float = 2.0,
        multiplier: float = 2.5,
    ) -> float:
        nonlocal vad_threshold, barge_in_threshold
        result = runtime.calibrate_ambient_noise(
            runtime.audio,
            server_enabled=runtime.get_server_enabled(),
            current_vad_threshold=vad_threshold,
            current_barge_in_threshold=barge_in_threshold,
            config_vad_threshold=config_vad_threshold,
            calibration_max_multiple=calibration_max_multiple,
            input_sample_rate=runtime.input_sample_rate,
            block_size=runtime.block_size,
            broadcast=runtime.broadcast,
            logger=runtime.logger,
            duration_seconds=duration_sec,
            multiplier=multiplier,
        )
        vad_threshold = result.vad_threshold
        barge_in_threshold = result.barge_in_threshold
        return vad_threshold

    vad_threshold = calibrate_noise_floor()
    runtime.set_noise_calibrator(calibrate_noise_floor)

    if runtime.get_listening_enabled():
        runtime.logger.info("Starting in always-listening mode (VAD-based)")
        runtime.logger.info(
            f"VAD Threshold set to: {vad_threshold:.3f} (adaptive)"
        )
        runtime.pipeline.transition_state("LISTENING")
    else:
        runtime.logger.info("Starting with VAD paused")
        runtime.logger.info(
            f"VAD Threshold set to: {vad_threshold:.3f} (adaptive)"
        )
        runtime.pipeline.transition_state("IDLE")
        runtime.broadcast("status", "IDLE")

    runtime.run_capture_loop(
        audio=runtime.audio,
        pipeline=runtime.pipeline,
        get_server_enabled=runtime.get_server_enabled,
        get_listening_enabled=runtime.get_listening_enabled,
        disable_listening=runtime.disable_listening,
        get_voice_mode=runtime.get_voice_mode,
        smooth_voice_mode=runtime.smooth_voice_mode,
        runtime_overrides=runtime.runtime_overrides,
        input_sample_rate=runtime.input_sample_rate,
        block_size=runtime.block_size,
        vad_threshold=vad_threshold,
        barge_in_threshold=barge_in_threshold,
        broadcast=runtime.broadcast,
        interrupt_current_response=runtime.interrupt_current_response,
        next_interaction_overrides=runtime.next_interaction_overrides,
        sound_cues=runtime.sound_cues,
        logger=runtime.logger,
        event_logger=runtime.event_logger,
    )
