"""Mutable frame-accounting state for the classic VAD loop."""

from __future__ import annotations

from enum import Enum, auto
from typing import Any


class CaptureFrameResult(Enum):
    CONTINUE = auto()
    PREMATURE_SILENCE = auto()
    COMPLETE = auto()


class ClassicCaptureTracker:
    def __init__(self, *, minimum_voiced_ms: float = 180.0) -> None:
        self.minimum_voiced_ms = minimum_voiced_ms
        self.speech_buffer: list[Any] = []
        self.is_recording = False
        self.silence_frames = 0
        self.voiced_ms = 0.0
        self.interaction_id = ""

    @staticmethod
    def _initial_buffer(preroll: Any) -> list[Any]:
        return [preroll] if len(preroll) > 0 else []

    def begin(self, interaction_id: str, preroll: Any) -> None:
        self.interaction_id = interaction_id
        self.speech_buffer = self._initial_buffer(preroll)
        self.is_recording = True
        self.silence_frames = 0
        self.voiced_ms = 0.0

    def begin_barge_in(self, preroll: Any) -> None:
        self.silence_frames = 0
        if not self.is_recording:
            self.speech_buffer = self._initial_buffer(preroll)
            self.is_recording = True

    def observe(
        self,
        frame: Any,
        *,
        volume: float,
        voice_threshold: float,
        silence_limit: int,
        frame_ms: float,
    ) -> CaptureFrameResult:
        self.speech_buffer.append(frame)
        if volume >= voice_threshold:
            self.voiced_ms += frame_ms
            self.silence_frames = 0
        else:
            self.silence_frames += 1
        if self.silence_frames <= silence_limit:
            return CaptureFrameResult.CONTINUE
        if self.voiced_ms < self.minimum_voiced_ms:
            return CaptureFrameResult.PREMATURE_SILENCE
        self.is_recording = False
        self.silence_frames = 0
        return CaptureFrameResult.COMPLETE

    def mark_dispatched(self) -> None:
        self.interaction_id = ""
