"""Steady-state VAD, barge-in, and capture loop for Classic Voice."""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

import numpy as np

from core.classic_barge_in import ClassicBargeInGate
from core.classic_capture import finish_classic_capture
from core.classic_capture_tracker import CaptureFrameResult, ClassicCaptureTracker


def _runtime_float(
    overrides: dict,
    key: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(overrides.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def run_classic_capture_loop(
    *,
    audio: Any,
    pipeline: Any,
    get_server_enabled: Callable[[], bool],
    get_listening_enabled: Callable[[], bool],
    disable_listening: Callable[[], None],
    get_voice_mode: Callable[[], str],
    smooth_voice_mode: str,
    runtime_overrides: dict,
    input_sample_rate: int,
    block_size: int,
    vad_threshold: float,
    barge_in_threshold: float,
    broadcast: Callable[[str, Any], None],
    interrupt_current_response: Callable[..., Any],
    next_interaction_overrides: dict,
    sound_cues: Any,
    logger: Any,
    event_logger: Callable[..., None],
    silence_seconds: float = 0.4,
    post_tts_cooldown: float = 0.75,
) -> None:
    """Run Classic Voice capture until the backend disables the server."""
    capture = ClassicCaptureTracker()
    barge_in_gate = ClassicBargeInGate()

    while get_server_enabled():
        if pipeline.illegal_transition:
            disable_listening()
            time.sleep(0.1)
            continue
        if not get_listening_enabled():
            time.sleep(0.1)
            continue
        frame = audio.read_frame()
        if frame is None:
            continue

        volume = np.linalg.norm(frame) * 10
        active_vad_threshold = _runtime_float(
            runtime_overrides, "vad_threshold", vad_threshold, 0.001, 20.0
        )
        active_barge_in_threshold = _runtime_float(
            runtime_overrides,
            "barge_in_threshold",
            barge_in_threshold,
            0.001,
            30.0,
        )
        active_silence_seconds = _runtime_float(
            runtime_overrides, "silence_seconds", silence_seconds, 0.1, 5.0
        )
        active_silence_threshold = int(
            (input_sample_rate / block_size) * active_silence_seconds
        )

        owner = audio.get_audio_owner() if audio else "NONE"
        try:
            from core.music_player import get_music_player

            music_playing = get_music_player().is_playing()
        except Exception:
            music_playing = False
        passive_listen = owner not in ("NONE", "STT", "MUSIC")
        if owner == "MUSIC" and music_playing:
            passive_listen = False

        in_echo_cooldown = (time.time() - pipeline.tts_finished_at) < post_tts_cooldown
        if (
            not passive_listen
            and get_voice_mode() != smooth_voice_mode
            and not pipeline.is_speaking
            and not capture.is_recording
            and not in_echo_cooldown
            and volume >= active_vad_threshold
            and pipeline.current_state == "LISTENING"
        ):
            interaction_id = str(uuid.uuid4())
            logger.info(
                f"[VAD] Speech detected (volume: {volume:.2f}, "
                f"threshold: {active_vad_threshold})"
            )
            event_logger(
                f"VAD_START rms={volume:.2f} threshold={active_vad_threshold}",
                stage="vad",
                interaction_id=interaction_id,
            )
            sound_cues.set_capture_active(True)
            capture.begin(interaction_id, audio.get_preroll())
            pipeline.transition_state("TRANSCRIBING", interaction_id=interaction_id)

        barge_in_suppressed = (
            pipeline.is_barge_in_suppressed()
            if hasattr(pipeline, "is_barge_in_suppressed")
            else False
        )
        barge_in = barge_in_gate.evaluate(
            now=time.time(),
            is_speaking=pipeline.is_speaking,
            volume=volume,
            threshold=active_barge_in_threshold,
            enabled=runtime_overrides.get("barge_in_enabled", True),
            suppressed=barge_in_suppressed,
        )
        if barge_in.pending:
            continue
        if barge_in.triggered:
            allowed = pipeline.current_state == "SPEAKING"
            logger.info(
                "!!! BARGE-IN TRIGGERED: Interrupting TTS "
                f"(rms={volume:.2f}, threshold={barge_in.effective_threshold:.2f}) !!!"
            )
            event_logger(
                f"BARGE_IN rms={volume:.2f} "
                f"threshold={barge_in.effective_threshold:.2f} "
                f"stage={pipeline.current_state} allowed={allowed}",
                stage="audio",
                interaction_id=pipeline.current_interaction_id,
            )
            broadcast(
                "barge_in",
                {
                    "interaction_id": pipeline.current_interaction_id,
                    "rms": float(volume),
                    "threshold": float(barge_in.effective_threshold),
                    "stage": str(pipeline.current_state),
                    "allowed": bool(allowed),
                },
            )
            interrupt_current_response("BARGE_IN", target_state="LISTENING")
            preroll = ()
            if not capture.is_recording:
                sound_cues.set_capture_active(True)
                preroll = audio.get_preroll()
            capture.begin_barge_in(preroll)

        if capture.is_recording and not passive_listen:
            capture_result = capture.observe(
                frame,
                volume=volume,
                voice_threshold=active_vad_threshold,
                silence_limit=active_silence_threshold,
                frame_ms=(block_size / input_sample_rate) * 1000,
            )
            if capture_result is CaptureFrameResult.PREMATURE_SILENCE:
                logger.debug(
                    f"[VAD] Ignoring premature VAD_END "
                    f"(voiced_ms={capture.voiced_ms:.1f})"
                )
                continue
            if capture_result is CaptureFrameResult.COMPLETE:
                event_logger(
                    "VAD_END", stage="vad", interaction_id=capture.interaction_id
                )
                sound_cues.set_capture_active(False)
                sound_cues.play(
                    "listening_end", interaction_id=capture.interaction_id, block=True
                )
                finish_classic_capture(
                    capture.speech_buffer,
                    audio=audio,
                    pipeline=pipeline,
                    interaction_id=capture.interaction_id,
                    voice_mode=get_voice_mode(),
                    smooth_voice_mode=smooth_voice_mode,
                    next_interaction_overrides=next_interaction_overrides,
                    sound_cues=sound_cues,
                    logger=logger,
                    event_logger=event_logger,
                )
                capture.mark_dispatched()
