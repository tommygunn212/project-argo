import numpy as np

from core.classic_capture_tracker import CaptureFrameResult, ClassicCaptureTracker


def frame(value=1.0):
    return np.array([value], dtype=np.float32)


def test_normal_start_resets_all_turn_state_and_keeps_preroll():
    tracker = ClassicCaptureTracker()
    tracker.voiced_ms = 500
    tracker.silence_frames = 9

    tracker.begin("turn-1", frame(0.5))

    assert tracker.interaction_id == "turn-1"
    assert tracker.is_recording is True
    assert tracker.voiced_ms == 0
    assert tracker.silence_frames == 0
    assert len(tracker.speech_buffer) == 1


def test_barge_in_preserves_accumulated_voice_but_resets_silence():
    tracker = ClassicCaptureTracker()
    tracker.voiced_ms = 120
    tracker.silence_frames = 4

    tracker.begin_barge_in(frame())

    assert tracker.voiced_ms == 120
    assert tracker.silence_frames == 0
    assert tracker.is_recording is True


def test_barge_in_during_active_capture_does_not_replace_existing_audio():
    tracker = ClassicCaptureTracker()
    existing = frame(0.25)
    tracker.begin("turn", existing)

    tracker.begin_barge_in(frame(0.75))

    assert len(tracker.speech_buffer) == 1
    assert tracker.speech_buffer[0] is existing


def test_premature_silence_does_not_end_capture():
    tracker = ClassicCaptureTracker(minimum_voiced_ms=180)
    tracker.begin("turn", np.array([], dtype=np.float32))

    result = tracker.observe(
        frame(0), volume=0, voice_threshold=1, silence_limit=0, frame_ms=32
    )

    assert result is CaptureFrameResult.PREMATURE_SILENCE
    assert tracker.is_recording is True


def test_sufficient_voice_then_silence_completes_capture():
    tracker = ClassicCaptureTracker(minimum_voiced_ms=64)
    tracker.begin("turn", np.array([], dtype=np.float32))
    assert tracker.observe(
        frame(), volume=2, voice_threshold=1, silence_limit=1, frame_ms=64
    ) is CaptureFrameResult.CONTINUE
    assert tracker.observe(
        frame(0), volume=0, voice_threshold=1, silence_limit=1, frame_ms=64
    ) is CaptureFrameResult.CONTINUE

    result = tracker.observe(
        frame(0), volume=0, voice_threshold=1, silence_limit=1, frame_ms=64
    )

    assert result is CaptureFrameResult.COMPLETE
    assert tracker.is_recording is False
    assert tracker.silence_frames == 0
    assert len(tracker.speech_buffer) == 3


def test_dispatch_clears_only_interaction_identity():
    tracker = ClassicCaptureTracker()
    tracker.begin("turn", frame())
    tracker.mark_dispatched()

    assert tracker.interaction_id == ""
    assert tracker.is_recording is True
    assert len(tracker.speech_buffer) == 1
