"""Classic pipeline speech-to-text processing behind a narrow interface."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable

import numpy as np


@dataclass(frozen=True)
class TranscriptionDependencies:
    logger: Any
    engine_manager: Any
    engine_name: str
    initial_prompt: str
    should_reject_audio: Callable[[float, float, float], tuple[bool, str]]
    record_timeline: Callable[..., None]
    broadcast: Callable[[str, Any], None]


@dataclass(frozen=True)
class TranscriptionOutcome:
    text: str
    metrics: dict[str, Any] | None = None


def transcribe_audio(
    dependencies: TranscriptionDependencies,
    audio_data: Any,
    interaction_id: str = "",
) -> TranscriptionOutcome:
    """Transcribe one audio buffer while containing engine failures."""
    manager = dependencies.engine_manager
    if manager is None or manager.model is None:
        dependencies.logger.error("[STT] Engine not initialized")
        return TranscriptionOutcome("")

    dependencies.logger.info(
        f"[STT] Starting transcription (engine={dependencies.engine_name})... "
        f"Audio len: {len(audio_data)}"
    )
    dependencies.record_timeline(
        "STT_START", stage="stt", interaction_id=interaction_id
    )

    try:
        duration_s = len(audio_data) / 16000.0 if len(audio_data) else 0
        rms = float(np.sqrt(np.mean(audio_data ** 2))) if len(audio_data) else 0.0
        peak = float(np.max(np.abs(audio_data))) if len(audio_data) else 0.0
        silence_ratio = (
            float(np.mean(np.abs(audio_data) < 0.01)) if len(audio_data) else 1.0
        )

        reject, reason = dependencies.should_reject_audio(
            rms, silence_ratio, duration_s
        )
        if reject:
            dependencies.logger.info(reason)
            dependencies.record_timeline(
                f"STT_DISCARD {reason}",
                stage="stt",
                interaction_id=interaction_id,
            )
            return TranscriptionOutcome("")

        if peak > 1.0:
            audio_data = audio_data / peak

        result = manager.transcribe(
            audio_data,
            language="en",
            beam_size=1 if dependencies.engine_name == "faster" else None,
            condition_on_previous_text=(
                False if dependencies.engine_name == "faster" else None
            ),
            initial_prompt=dependencies.initial_prompt or None,
        )
        text = result["text"]
        engine = result["engine"]
        duration_ms = result["duration_ms"]

        for index, segment in enumerate(result.get("segments", [])):
            segment_text = (
                segment.text if hasattr(segment, "text") else segment.get("text", "")
            )
            if hasattr(segment, "avg_logprob"):
                confidence = np.exp(segment.avg_logprob)
                dependencies.logger.info(
                    f"  Seg {index}: '{segment_text}' (conf={confidence:.2f})"
                )
            else:
                dependencies.logger.info(f"  Seg {index}: '{segment_text}'")

        confidence_proxy = 0.0
        if duration_s > 0:
            confidence_proxy = min(
                1.0,
                (len(text) / max(1.0, duration_s * 10)) * (1.0 - silence_ratio),
            )

        dependencies.logger.info(
            f"[STT] Done in {duration_ms:.0f}ms (engine={engine}): '{text}'"
        )
        dependencies.record_timeline(
            f"STT_DONE engine={engine} len={len(text)} rms={rms:.4f} "
            f"peak={peak:.4f} silence={silence_ratio:.2f} "
            f"conf={confidence_proxy:.2f}",
            stage="stt",
            interaction_id=interaction_id,
        )
        metrics = {
            "engine": engine,
            "text_len": len(text),
            "duration_s": duration_s,
            "rms": rms,
            "peak": peak,
            "silence_ratio": silence_ratio,
            "confidence": confidence_proxy,
        }
        dependencies.broadcast(
            "stt_metrics", {"interaction_id": interaction_id, **metrics}
        )
        return TranscriptionOutcome(text, metrics)
    except Exception as exc:
        dependencies.logger.error(f"[STT] Failed: {exc}", exc_info=True)
        dependencies.record_timeline(
            "STT_ERROR", stage="stt", interaction_id=interaction_id
        )
        return TranscriptionOutcome("")
