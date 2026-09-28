"""Characterization tests for live classic-pipeline tuning overrides."""

from core.pipeline import ArgoPipeline


def _pipeline(overrides: dict) -> ArgoPipeline:
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.runtime_overrides = overrides
    pipeline._stt_min_rms_threshold = 0.005
    pipeline._stt_silence_ratio_threshold = 0.90
    pipeline._stt_min_duration_s = 0.30
    pipeline._vad_silence_pad_ms = 300
    pipeline._tts_min_confidence = 0.55
    pipeline._personal_mode_min_confidence = 0.45
    return pipeline


def test_runtime_tuning_applies_all_supported_overrides():
    pipeline = _pipeline(
        {
            "stt_min_rms_threshold": "0.02",
            "stt_silence_ratio_threshold": 0.75,
            "stt_min_duration_s": 0.8,
            "vad_silence_pad_ms": 650.9,
            "tts_min_confidence": 0.7,
            "personal_mode_min_confidence": 0.6,
        }
    )

    pipeline.apply_runtime_tuning()

    assert pipeline._stt_min_rms_threshold == 0.02
    assert pipeline._stt_silence_ratio_threshold == 0.75
    assert pipeline._stt_min_duration_s == 0.8
    assert pipeline._vad_silence_pad_ms == 650
    assert pipeline._tts_min_confidence == 0.7
    assert pipeline._personal_mode_min_confidence == 0.6


def test_runtime_tuning_clamps_values_to_safe_ranges():
    pipeline = _pipeline(
        {
            "stt_min_rms_threshold": 5,
            "stt_silence_ratio_threshold": -1,
            "stt_min_duration_s": 12,
            "vad_silence_pad_ms": -30,
            "tts_min_confidence": 9,
            "personal_mode_min_confidence": -4,
        }
    )

    pipeline.apply_runtime_tuning()

    assert pipeline._stt_min_rms_threshold == 0.2
    assert pipeline._stt_silence_ratio_threshold == 0.0
    assert pipeline._stt_min_duration_s == 5.0
    assert pipeline._vad_silence_pad_ms == 0
    assert pipeline._tts_min_confidence == 1.0
    assert pipeline._personal_mode_min_confidence == 0.0


def test_invalid_runtime_values_preserve_current_thresholds():
    pipeline = _pipeline(
        {
            "stt_min_rms_threshold": "not-a-number",
            "stt_silence_ratio_threshold": None,
        }
    )

    pipeline.apply_runtime_tuning()

    assert pipeline._stt_min_rms_threshold == 0.005
    assert pipeline._stt_silence_ratio_threshold == 0.90
    assert pipeline._stt_min_duration_s == 0.30
    assert pipeline._vad_silence_pad_ms == 300
    assert pipeline._tts_min_confidence == 0.55
    assert pipeline._personal_mode_min_confidence == 0.45

