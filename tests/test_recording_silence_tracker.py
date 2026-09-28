import pytest

from core.recording_silence_tracker import RecordingSilenceTracker


def observe(tracker, elapsed, total, *, speech=False, silence=True, chunk=100):
    return tracker.observe(
        elapsed_seconds=elapsed,
        total_samples=total,
        chunk_samples=chunk,
        is_speech=speech,
        is_silence=silence,
    )


def test_silence_before_speech_never_starts_the_stop_timer():
    tracker = RecordingSilenceTracker(silence_samples=200, minimum_samples=100)

    assert observe(tracker, 0.1, 100).stop_for_silence is False
    assert observe(tracker, 0.2, 200).stop_for_silence is False
    assert tracker.consecutive_silence_samples == 0


def test_speech_start_is_reported_once():
    tracker = RecordingSilenceTracker(silence_samples=200, minimum_samples=100)

    assert observe(tracker, 0.1, 100, speech=True, silence=False).speech_started is True
    assert observe(tracker, 0.2, 200, speech=True, silence=False).speech_started is False
    assert tracker.speech_detected_at == 0.1


def test_continuous_post_speech_silence_stops_after_threshold():
    tracker = RecordingSilenceTracker(silence_samples=200, minimum_samples=100)
    observe(tracker, 0.1, 100, speech=True, silence=False)

    assert observe(tracker, 0.2, 200).stop_for_silence is False
    decision = observe(tracker, 0.3, 300)

    assert decision.stop_for_silence is True
    assert decision.silence_duration == pytest.approx(0.1)


def test_voice_resets_accumulated_silence():
    tracker = RecordingSilenceTracker(silence_samples=200, minimum_samples=100)
    observe(tracker, 0.1, 100, speech=True, silence=False)
    observe(tracker, 0.2, 200)
    observe(tracker, 0.3, 300, speech=True, silence=False)

    assert observe(tracker, 0.4, 400).stop_for_silence is False
    assert observe(tracker, 0.5, 500).stop_for_silence is True


def test_minimum_recording_length_still_gates_silence_stop():
    tracker = RecordingSilenceTracker(silence_samples=100, minimum_samples=500)
    observe(tracker, 0.1, 100, speech=True, silence=False)

    assert observe(tracker, 0.2, 200).stop_for_silence is False
    assert observe(tracker, 0.5, 500, chunk=0).stop_for_silence is True
