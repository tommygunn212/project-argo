"""Silero voice activity detection for the classic recording loop.

The classic path decided "is this speech?" by comparing chunk RMS to a
fixed number. Fans, keyboard noise and the speaker's own output all clear
an energy threshold, so the turn stayed open on noise and the thresholds
had been dragged down far enough (0.0005 normalized) to trigger on almost
anything.

livekit-plugins-silero was already installed for the realtime path and
unused here. This wraps its ONNX model in a plain synchronous gate: feed
it audio chunks, get back a speech probability. No event loop, no LiveKit
session, nothing to await.

Everything degrades: if the model will not load, `available` is False and
callers fall back to their own energy check rather than losing the mic.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger("ARGO.VAD")

# Silero is trained on 8 kHz and 16 kHz only, in fixed-size windows.
WINDOW_SAMPLES = {8000: 256, 16000: 512}

DEFAULT_THRESHOLD = 0.5


class SileroGate:
    """Speech/not-speech on int16 or float32 audio chunks.

    The model is stateful across windows, which is the point - it reads
    context rather than instantaneous loudness. Call `reset()` between
    recordings so one turn's tail does not colour the next one's start.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = DEFAULT_THRESHOLD,
        force_cpu: bool = True,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.threshold = float(threshold)
        self._window = WINDOW_SAMPLES.get(self.sample_rate)
        self._model = None
        self._residual = np.zeros(0, dtype=np.float32)
        self._last_probability: Optional[float] = None

        if self._window is None:
            logger.warning(
                "[VAD] Silero supports 8k/16k only; %s Hz falls back to energy detection",
                self.sample_rate,
            )
            return

        try:
            from livekit.plugins.silero import onnx_model

            session = onnx_model.new_inference_session(force_cpu=force_cpu)
            self._model = onnx_model.OnnxModel(
                onnx_session=session, sample_rate=self.sample_rate
            )
            logger.info("[VAD] Silero loaded (%s Hz, threshold %.2f)", self.sample_rate, self.threshold)
        except Exception:
            self._model = None
            logger.exception("[VAD] Silero unavailable; falling back to energy detection")

    @property
    def available(self) -> bool:
        return self._model is not None

    @property
    def last_probability(self) -> Optional[float]:
        """Probability from the most recent chunk, for logging."""
        return self._last_probability

    def reset(self) -> None:
        """Clear the model's memory and any partial window."""
        self._residual = np.zeros(0, dtype=np.float32)
        self._last_probability = None
        if self._model is not None:
            try:
                self._model.reset()
            except Exception:
                logger.debug("[VAD] reset failed", exc_info=True)

    def probability(self, chunk) -> Optional[float]:
        """Highest speech probability across the windows in this chunk.

        Returns None when the gate is unavailable - which means "I could
        not judge", never "no speech". Callers must fall back rather than
        treat None as silence.
        """
        if self._model is None:
            return None
        try:
            samples = _to_float32(chunk)
        except Exception:
            logger.debug("[VAD] unreadable chunk", exc_info=True)
            return None

        buffer = np.concatenate((self._residual, samples)) if self._residual.size else samples
        window = self._window
        best: Optional[float] = None
        offset = 0
        try:
            while buffer.size - offset >= window:
                score = float(self._model(buffer[offset:offset + window]))
                best = score if best is None else max(best, score)
                offset += window
        except Exception:
            logger.exception("[VAD] inference failed; disabling Silero for this session")
            self._model = None
            return None

        # Keep the tail so windows stay aligned across chunk boundaries.
        self._residual = buffer[offset:].copy()
        if best is not None:
            self._last_probability = best
        return best

    def is_speech(self, chunk) -> Optional[bool]:
        """True/False, or None when the gate could not judge."""
        score = self.probability(chunk)
        if score is None:
            return None
        return score >= self.threshold


def _to_float32(chunk) -> np.ndarray:
    """Flatten to mono float32 in [-1, 1], whatever the caller had."""
    array = np.asarray(chunk)
    if array.ndim > 1:
        array = array.reshape(array.shape[0], -1).mean(axis=1)
    array = array.reshape(-1)
    if array.dtype == np.int16:
        return (array.astype(np.float32) / 32768.0)
    if array.dtype == np.int32:
        return (array.astype(np.float32) / 2147483648.0)
    return array.astype(np.float32, copy=False)
