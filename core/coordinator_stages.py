"""Explicit interaction stages used by :mod:`core.coordinator`."""

from __future__ import annotations

from datetime import datetime
import io
from dataclasses import dataclass
import re
import time
from typing import Any, Optional

from core.intent_parser import Intent, IntentType, is_system_keyword, normalize_system_text


def capture_audio_stage(
    coordinator: Any,
    initial_frames: Optional[list] = None,
) -> bytes:
    """Record one utterance and return a WAV payload for STT."""
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] "
        f"Recording (max {coordinator.MAX_RECORDING_DURATION}s, stops on "
        f"{coordinator.SILENCE_DURATION}s silence)..."
    )
    coordinator.current_probe.mark("recording_start")

    if coordinator.on_recording_start:
        try:
            coordinator.on_recording_start()
        except Exception as exc:
            coordinator.logger.debug(
                f"[Coordinator] on_recording_start callback error: {exc}"
            )

    audio = coordinator._record_with_silence_detection(
        initial_frames=initial_frames
    )
    coordinator.current_probe.mark("recording_end")

    if coordinator.on_recording_stop:
        try:
            coordinator.on_recording_stop()
        except Exception as exc:
            coordinator.logger.debug(
                f"[Coordinator] on_recording_stop callback error: {exc}"
            )

    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Recorded {len(audio)} "
        f"samples ({len(audio) / coordinator.AUDIO_SAMPLE_RATE:.2f}s)"
    )

    from scipy.io import wavfile

    audio_buffer = io.BytesIO()
    wavfile.write(audio_buffer, coordinator.AUDIO_SAMPLE_RATE, audio)
    audio_bytes = audio_buffer.getvalue()
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Audio buffer: "
        f"{len(audio_bytes)} bytes"
    )
    return audio_bytes


def transcribe_audio_stage(coordinator: Any, audio_bytes: bytes) -> str:
    """Transcribe one WAV payload and update observer/timing state."""
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Transcribing audio..."
    )
    coordinator.current_probe.mark("stt_start")
    text = coordinator.stt.transcribe(
        audio_bytes, coordinator.AUDIO_SAMPLE_RATE
    )
    coordinator.logger.info(f"[STT RAW] '{text}'")
    coordinator.current_probe.mark("stt_end")

    coordinator._last_wake_timestamp = datetime.now()
    coordinator._last_transcript = text
    coordinator.dynamic_silence_timeout = coordinator.get_dynamic_timeout(text)
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Transcribed: '{text}'"
    )
    return text


@dataclass(frozen=True)
class TranscriptStageResult:
    continue_processing: bool
    interaction_result: bool
    text: str
    stt_confidence: float


def process_transcript_stage(
    coordinator: Any,
    text: str,
    overrides: dict[str, Any],
) -> TranscriptStageResult:
    """Admit, normalize, or terminally handle a raw transcript."""
    if overrides.get("force_passive_listening"):
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] Passive listening "
            "override active; skipping intent/command"
        )
        return TranscriptStageResult(False, False, text, 0.0)

    if coordinator.last_response_text:
        similarity = coordinator._similarity_ratio(
            text, coordinator.last_response_text
        )
        if similarity >= 0.80:
            coordinator.logger.info(
                f"[Iteration {coordinator.interaction_count}] Self-echo detected "
                f"(similarity={similarity:.2f}); discarding transcript"
            )
            coordinator.interaction_count -= 1
            return TranscriptStageResult(False, False, text, 0.0)

    run_triggers = {"run it", "test it", "run", "test"}
    if (
        coordinator._last_built_script
        and text.lower().strip() in run_triggers
    ):
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] Running sandbox script: "
            f"{coordinator._last_built_script}"
        )
        output = coordinator.builder.test_run(coordinator._last_built_script)
        analysis_intent = Intent(
            intent_type=IntentType.DEVELOP,
            confidence=1.0,
            raw_text=(
                f"The script '{coordinator._last_built_script}' was executed. "
                f"Output:\n{output}\nSummarize the result and suggest next steps."
            ),
        )
        response_text = coordinator.generator.generate(
            analysis_intent, coordinator.memory
        )
        coordinator._last_response = response_text
        coordinator.last_response_text = response_text
        coordinator._safe_speak(
            response_text, interaction_id=coordinator.interaction_id
        )
        coordinator.memory.append(
            user_utterance=text,
            parsed_intent=analysis_intent.intent_type.value,
            generated_response=response_text,
        )
        coordinator._last_utterance_time = time.time()
        return TranscriptStageResult(False, True, text, 0.0)

    if not text or not text.strip():
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] Empty transcription "
            "(silence only), skipping..."
        )
        coordinator.interaction_count -= 1
        return TranscriptStageResult(False, False, text, 0.0)

    try:
        stt_metrics = coordinator.stt.get_last_metrics()
    except Exception:
        stt_metrics = None
    stt_confidence = 0.0
    if stt_metrics:
        try:
            stt_confidence = float(stt_metrics.get("confidence", 0.0))
        except Exception:
            stt_confidence = 0.0

    text = normalize_system_text(text)
    if stt_confidence < 0.35 or not text.strip():
        if is_system_keyword(text):
            coordinator.logger.info(
                f"[Iteration {coordinator.interaction_count}] Low STT confidence "
                f"({stt_confidence:.2f}) but whitelisted system intent: {text}"
            )
        elif re.search(r"\bcount\b", text, flags=re.IGNORECASE):
            coordinator.logger.info(
                f"[Iteration {coordinator.interaction_count}] Low STT confidence "
                f"({stt_confidence:.2f}) but count detected; continuing"
            )
        elif stt_confidence < 0.10 or not text.strip():
            coordinator.logger.info(
                f"[Iteration {coordinator.interaction_count}] Low STT confidence "
                f"({stt_confidence:.2f}); skipping"
            )
            if (
                not coordinator._low_conf_notice_given
                and coordinator.runtime_overrides.get("tts_enabled", True)
            ):
                coordinator._safe_speak(
                    "I didn’t catch that clearly. Try saying it as a full sentence.",
                    interaction_id=coordinator.interaction_id,
                )
                coordinator._low_conf_notice_given = True
            coordinator.interaction_count -= 1
            return TranscriptStageResult(
                False, False, text, stt_confidence
            )

    return TranscriptStageResult(True, False, text, stt_confidence)
