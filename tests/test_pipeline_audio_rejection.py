"""Boundary contract tests for classic audio rejection policy."""

from core.pipeline import ArgoPipeline


def _pipeline(*, personal_mode=False):
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.runtime_overrides = {"personal_mode": personal_mode}
    pipeline._stt_min_duration_s = 0.3
    pipeline._stt_min_rms_threshold = 0.01
    pipeline._stt_silence_ratio_threshold = 0.8
    return pipeline


def test_personal_mode_accepts_cloud_viable_audio_before_normal_thresholds():
    pipeline = _pipeline(personal_mode=True)

    assert pipeline._should_reject_audio(0.002, 1.0, 0.2) == (False, "")


def test_personal_mode_short_or_quieter_audio_still_uses_normal_thresholds():
    pipeline = _pipeline(personal_mode=True)

    rejected, _ = pipeline._should_reject_audio(0.0019, 1.0, 0.2)
    assert rejected is True
    rejected, _ = pipeline._should_reject_audio(0.002, 1.0, 0.199)
    assert rejected is True


def test_duration_floor_and_rms_floor_each_accept_audio_independently():
    pipeline = _pipeline()

    assert pipeline._should_reject_audio(0.0, 1.0, 0.3) == (False, "")
    assert pipeline._should_reject_audio(0.01, 1.0, 0.0) == (False, "")


def test_non_silent_audio_below_other_floors_is_accepted():
    pipeline = _pipeline()

    assert pipeline._should_reject_audio(0.0, 0.799, 0.0) == (False, "")


def test_rejected_audio_reports_stable_diagnostics():
    pipeline = _pipeline()

    assert pipeline._should_reject_audio(0.001, 0.95, 0.05) == (
        True,
        "VAD discard: rms=0.0010, duration_ms=50, silence_ratio=0.95",
    )
