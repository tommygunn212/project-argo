"""Microphone capture mechanics for the classic coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

from core.recording_silence_tracker import RecordingSilenceTracker


@dataclass(frozen=True)
class RecordingConfig:
    sample_rate: int
    minimum_duration: float
    dynamic_silence_timeout: float
    maximum_duration: float
    rms_speech_threshold: float
    silence_threshold: float
    silence_timeout_label: float
    record_debug: bool
    input_device_index: int | None


@dataclass(frozen=True)
class RecordingHooks:
    logger: Any
    should_abort: Callable[[], bool]
    speech_gate: Callable[[], Any]
    get_preroll: Callable[[], list]
    set_stream_state: Callable[[Any, bool], None]
    event_logger: Callable[[str], None]
    last_transcript: Callable[[], str]


def _normalized_audio(chunks: list[Any], logger: Any, debug: bool) -> np.ndarray:
    if not chunks:
        return np.array([], dtype=np.int16)
    audio = np.concatenate(chunks, axis=0)
    peak = np.max(np.abs(audio.astype(float)))
    if peak > 0:
        audio = (audio.astype(float) / peak * 32767).astype(np.int16)
        if debug:
            logger.debug(f"[Record] Audio normalized (peak was {peak:.0f})")
    return audio


def record_with_silence_detection(
    config: RecordingConfig,
    hooks: RecordingHooks,
    *,
    stream_factory: Callable[..., Any],
    device_query: Callable[[], Any],
    initial_frames: Optional[list] = None,
) -> np.ndarray:
    """Capture one utterance and guarantee stream cleanup on every exit path."""
    import time

    chunk_samples = int(config.sample_rate * 0.1)
    min_samples = int(config.sample_rate * config.minimum_duration)
    silence_samples = int(config.sample_rate * config.dynamic_silence_timeout)
    max_samples = int(config.sample_rate * config.maximum_duration)
    tracker = RecordingSilenceTracker(
        silence_samples=silence_samples,
        minimum_samples=min_samples,
    )
    audio_buffer = []
    total_samples = 0
    stop_reason = None
    rms_samples = []

    preroll_frames = initial_frames if initial_frames is not None else []
    if initial_frames is None:
        try:
            preroll_frames = hooks.get_preroll()
        except Exception as error:
            hooks.logger.debug(f"[Record] Could not retrieve pre-roll buffer: {error}")
    if preroll_frames:
        for frame in preroll_frames:
            audio_buffer.append(frame)
            total_samples += frame.shape[0]
        if config.record_debug:
            hooks.logger.info(
                f"[Record] Pre-roll: {len(preroll_frames)} frames "
                f"({total_samples/config.sample_rate:.2f}s)"
            )

    recording_start_time = time.time()
    stream = None
    try:
        if config.record_debug:
            hooks.logger.info("[Record] Available audio devices:")
            for index, device in enumerate(device_query()):
                hooks.logger.info(
                    f"  [{index}] {device['name']} (in={device['max_input_channels']}, "
                    f"out={device['max_output_channels']})"
                )
        stream = stream_factory(
            channels=1,
            samplerate=config.sample_rate,
            dtype=np.int16,
            device=config.input_device_index,
        )
        hooks.set_stream_state(stream, True)
        stream.start()
        hooks.event_logger("MIC OPEN")
        vad = hooks.speech_gate()
        if vad is not None:
            vad.reset()
        chunk_count = 0

        while total_samples < max_samples:
            if hooks.should_abort():
                stop_reason = "speaking_gate"
                if config.record_debug:
                    hooks.logger.info("[Record] Aborting: speaking gate active")
                break
            chunk, _ = stream.read(chunk_samples)
            if chunk.size == 0:
                break
            audio_buffer.append(chunk)
            total_samples += chunk.shape[0]
            elapsed = time.time() - recording_start_time
            rms = np.sqrt(np.mean(chunk.astype(float) ** 2)) / 32768.0
            rms_samples.append(rms)
            chunk_count += 1
            chunk_is_speech = vad.is_speech(chunk) if vad is not None else None
            if chunk_is_speech is None:
                chunk_is_speech = rms > config.rms_speech_threshold
                chunk_is_silence = rms < config.silence_threshold
            else:
                chunk_is_silence = not chunk_is_speech
            if chunk_count % 20 == 0:
                hooks.logger.debug(f"[AudioDebug] RMS={rms:.4f} (elapsed={elapsed:.2f}s)")
            recent = rms_samples[-25:] if len(rms_samples) >= 25 else rms_samples
            if elapsed > 2.5 and np.mean(recent) < 0.002:
                stop_reason = "no_voice_detected"
                hooks.logger.warning(
                    "[Record] No voice detected (avg RMS < 0.002 after 2.5s), aborting early"
                )
                break
            silence = tracker.observe(
                elapsed_seconds=elapsed,
                total_samples=total_samples,
                chunk_samples=chunk.shape[0],
                is_speech=chunk_is_speech,
                is_silence=chunk_is_silence,
            )
            if silence.speech_started and config.record_debug:
                hooks.logger.info(f"[Record] Speech detected at {elapsed:.3f}s (RMS={rms:.4f})")
            if silence.stop_for_silence:
                stop_reason = "silence"
                if config.record_debug:
                    hooks.logger.info(
                        f"[Record] Silence detected ({silence.silence_duration:.2f}s >= "
                        f"{config.silence_timeout_label}s), stopping recording "
                        f"({total_samples/config.sample_rate:.2f}s recorded)"
                    )
                break
            if total_samples >= max_samples:
                stop_reason = "max_duration"
                filtered = rms_samples[3:] if len(rms_samples) > 3 else rms_samples
                average = np.mean(filtered) if filtered else 0.0
                hooks.logger.warning(
                    f"[Record] MAX DURATION REACHED (15.0s) - stopping recording | "
                    f"total_samples={total_samples}, avg_rms={average:.2f}"
                )
                break
    except Exception as error:
        hooks.logger.error(f"[Record] Error during audio recording: {error}")
        raise
    finally:
        if stream:
            try:
                stream.stop()
                stream.close()
            except Exception as error:
                hooks.logger.warning(f"[Record] Error closing stream: {error}")
        hooks.event_logger("MIC CLOSE")
        hooks.set_stream_state(None, False)

    if config.record_debug and rms_samples:
        filtered = rms_samples[3:] if len(rms_samples) > 3 else rms_samples
        average = np.mean(filtered) if filtered else 0.0
        hooks.logger.info("[Record] Recording Summary:")
        hooks.logger.info(
            f"  Duration: {total_samples/config.sample_rate:.2f}s "
            f"(minimum: {config.minimum_duration}s)"
        )
        hooks.logger.info(
            f"  RMS average: {average:.4f} (normalized 0-1, "
            f"threshold: {config.rms_speech_threshold})"
        )
        hooks.logger.info(
            f"  Speech detected at: {tracker.speech_detected_at:.3f}s"
            if tracker.speech_detected_at
            else "  Speech: NOT detected"
        )
        hooks.logger.info(f"  Stop reason: {stop_reason}")
        hooks.logger.info(f"  Silence threshold: {config.silence_threshold} (absolute RMS)")
        hooks.logger.info(f"  Silence timeout: {config.silence_timeout_label}s")
        if hooks.last_transcript():
            hooks.logger.info(f"  Transcript: '{hooks.last_transcript()}'")
    return _normalized_audio(audio_buffer, hooks.logger, config.record_debug)
