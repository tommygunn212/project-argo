"""Bounded speech-onset detection for the classic coordinator."""

from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np


@dataclass(frozen=True)
class SpeechStartConfig:
    sample_rate: int
    preroll_buffer_ms_max: int
    rms_speech_threshold: float
    input_device_index: int | None


@dataclass(frozen=True)
class SpeechStartDependencies:
    get_audio_state: Callable[[], str]
    speaking_state: str
    should_stop: Callable[[], bool]
    stream_factory: Callable[..., Any]
    set_stream_state: Callable[[Any, bool], None]
    time_now: Callable[[], float]
    logger: Any


def wait_for_speech_start(
    config: SpeechStartConfig,
    dependencies: SpeechStartDependencies,
    max_wait_seconds: float | None,
) -> Optional[list]:
    """Wait for RMS speech onset and return the bounded pre-roll frames."""

    chunk_samples = int(config.sample_rate * 0.1)
    preroll_capacity = max(1, int(config.preroll_buffer_ms_max / 100))
    preroll_frames = []
    start_time = dependencies.time_now()
    stream = None
    try:
        if dependencies.get_audio_state() == dependencies.speaking_state:
            return None
        stream = dependencies.stream_factory(
            channels=1,
            samplerate=config.sample_rate,
            dtype=np.int16,
            device=config.input_device_index,
        )
        dependencies.set_stream_state(stream, True)
        stream.start()

        while True:
            if (
                dependencies.should_stop()
                or dependencies.get_audio_state() == dependencies.speaking_state
            ):
                return None
            if (
                max_wait_seconds is not None
                and dependencies.time_now() - start_time >= max_wait_seconds
            ):
                return None

            frame, _ = stream.read(chunk_samples)
            if frame.size == 0:
                continue
            preroll_frames.append(frame.copy())
            if len(preroll_frames) > preroll_capacity:
                preroll_frames.pop(0)
            rms = np.sqrt(np.mean(frame.astype(float) ** 2)) / 32768.0
            if rms > config.rms_speech_threshold:
                return preroll_frames
    except Exception as exc:
        dependencies.logger.debug(f"[Listen] Speech-start detection failed: {exc}")
        return None
    finally:
        if stream:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:
                dependencies.logger.debug(f"[Listen] Error closing stream: {exc}")
        dependencies.set_stream_state(None, False)
