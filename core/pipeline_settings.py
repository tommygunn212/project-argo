"""Validated configuration values used to initialize the classic pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.config import (
    MIN_TTS_CONFIDENCE,
    MIN_TTS_TEXT_LEN,
    PERSONAL_MODE_MIN_CONFIDENCE,
    PERSONAL_MODE_MIN_TEXT_LEN,
)


@dataclass(frozen=True)
class PipelineSettings:
    conversation_buffer_size: int = 24
    conversation_ledger_size: int = 10
    tts_min_text_length: int = MIN_TTS_TEXT_LEN
    tts_min_confidence: float = MIN_TTS_CONFIDENCE
    personal_mode_min_confidence: float = PERSONAL_MODE_MIN_CONFIDENCE
    personal_mode_min_text_length: int = PERSONAL_MODE_MIN_TEXT_LEN
    stt_prompt_profile: str = "general"
    stt_initial_prompt: str = ""
    stt_min_rms_threshold: float = 0.005
    stt_silence_ratio_threshold: float = 0.90
    stt_min_duration_seconds: float = 0.3
    vad_silence_pad_ms: int = 300
    strict_lab_mode: bool = False


def load_pipeline_settings(config: Any, runtime_overrides: dict) -> PipelineSettings:
    """Resolve optional config values and clamp safety-sensitive thresholds."""
    defaults = PipelineSettings()
    values = {
        "conversation_buffer_size": defaults.conversation_buffer_size,
        "conversation_ledger_size": defaults.conversation_ledger_size,
        "tts_min_text_length": defaults.tts_min_text_length,
        "tts_min_confidence": defaults.tts_min_confidence,
        "personal_mode_min_confidence": defaults.personal_mode_min_confidence,
        "personal_mode_min_text_length": defaults.personal_mode_min_text_length,
        "stt_prompt_profile": defaults.stt_prompt_profile,
        "stt_initial_prompt": defaults.stt_initial_prompt,
        "stt_min_rms_threshold": defaults.stt_min_rms_threshold,
        "stt_silence_ratio_threshold": defaults.stt_silence_ratio_threshold,
        "stt_min_duration_seconds": defaults.stt_min_duration_seconds,
        "vad_silence_pad_ms": defaults.vad_silence_pad_ms,
        "strict_lab_mode": defaults.strict_lab_mode,
    }
    try:
        if config is not None:
            values["conversation_buffer_size"] = int(
                config.get("conversation.buffer_size", defaults.conversation_buffer_size)
            )
            values["conversation_ledger_size"] = int(
                config.get("conversation.ledger_size", defaults.conversation_ledger_size)
            )
            profile = str(
                config.get("speech_to_text.prompt_profile", defaults.stt_prompt_profile)
            )
            values["stt_prompt_profile"] = profile
            profiles = config.get("speech_to_text.initial_prompt_profiles", {}) or {}
            values["stt_initial_prompt"] = str(profiles.get(profile, ""))
            values["stt_min_rms_threshold"] = float(
                config.get(
                    "speech_to_text.min_rms_threshold",
                    defaults.stt_min_rms_threshold,
                )
            )
            values["stt_silence_ratio_threshold"] = float(
                config.get(
                    "speech_to_text.silence_ratio_threshold",
                    defaults.stt_silence_ratio_threshold,
                )
            )
            values["stt_min_duration_seconds"] = float(
                config.get(
                    "speech_to_text.min_duration_seconds",
                    defaults.stt_min_duration_seconds,
                )
            )
            values["vad_silence_pad_ms"] = int(
                config.get("audio.vad_silence_pad_ms", defaults.vad_silence_pad_ms)
            )
            values["strict_lab_mode"] = bool(
                config.get("modes.strict_lab_mode", defaults.strict_lab_mode)
            )
            values["tts_min_text_length"] = int(
                config.get("guards.tts.min_text_length", defaults.tts_min_text_length)
            )
            values["tts_min_confidence"] = float(
                config.get("guards.tts.min_confidence", defaults.tts_min_confidence)
            )
            values["personal_mode_min_confidence"] = float(
                config.get(
                    "guards.stt.personal_min_confidence",
                    defaults.personal_mode_min_confidence,
                )
            )
            values["personal_mode_min_text_length"] = int(
                config.get(
                    "guards.stt.personal_min_text_length",
                    defaults.personal_mode_min_text_length,
                )
            )
    except Exception:
        pass

    values["tts_min_text_length"] = max(1, int(values["tts_min_text_length"]))
    values["personal_mode_min_text_length"] = max(
        1, int(values["personal_mode_min_text_length"])
    )
    values["tts_min_confidence"] = max(
        0.0, min(1.0, float(values["tts_min_confidence"]))
    )
    values["personal_mode_min_confidence"] = max(
        0.0, min(1.0, float(values["personal_mode_min_confidence"]))
    )
    values["stt_min_duration_seconds"] = max(
        float(values["stt_min_duration_seconds"]),
        int(values["vad_silence_pad_ms"]) / 1000.0,
    )
    if "strict_lab_mode" in runtime_overrides:
        values["strict_lab_mode"] = bool(runtime_overrides["strict_lab_mode"])
    return PipelineSettings(**values)
