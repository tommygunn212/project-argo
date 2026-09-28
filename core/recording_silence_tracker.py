"""Pure speech/silence timing state for coordinator microphone capture."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SilenceDecision:
    speech_started: bool = False
    stop_for_silence: bool = False
    silence_duration: float = 0.0


class RecordingSilenceTracker:
    """Track continuous post-speech silence without owning audio I/O."""

    def __init__(self, *, silence_samples: int, minimum_samples: int) -> None:
        self.silence_samples = silence_samples
        self.minimum_samples = minimum_samples
        self.speech_detected = False
        self.speech_detected_at: float | None = None
        self.silence_started_at: float | None = None
        self.consecutive_silence_samples = 0

    def observe(
        self,
        *,
        elapsed_seconds: float,
        total_samples: int,
        chunk_samples: int,
        is_speech: bool,
        is_silence: bool,
    ) -> SilenceDecision:
        speech_started = False
        if not self.speech_detected and is_speech:
            self.speech_detected = True
            self.speech_detected_at = elapsed_seconds
            speech_started = True

        if not self.speech_detected:
            return SilenceDecision()

        if is_silence:
            if self.silence_started_at is None:
                self.silence_started_at = elapsed_seconds
            self.consecutive_silence_samples += chunk_samples
        else:
            self.consecutive_silence_samples = 0
            self.silence_started_at = None

        should_stop = (
            self.consecutive_silence_samples >= self.silence_samples
            and total_samples >= self.minimum_samples
        )
        duration = (
            elapsed_seconds - self.silence_started_at
            if should_stop and self.silence_started_at is not None
            else 0.0
        )
        return SilenceDecision(speech_started, should_stop, duration)
