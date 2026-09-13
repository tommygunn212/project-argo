"""A wedged turn must not be able to deafen ARGO permanently.

run_interaction holds processing_lock for the whole turn. If a turn never
finishes - blocked in a network call or an audio write - the lock stays held
and every later input is dropped as "System busy". Interrupting does not clear
it, so Stop Server left ARGO stalled until the process was killed.
"""

import threading
import time

import pytest

from core.pipeline import ArgoPipeline


class _FakeAudio:
    def __init__(self):
        self.calls = []

    def force_release_audio(self, *a, **k):
        self.calls.append("force_release_audio")

    def stop_playback(self):
        self.calls.append("stop_playback")

    def clear_buffers(self):
        self.calls.append("clear_buffers")


@pytest.fixture
def pipeline():
    """A pipeline with only the pieces hard_reset touches."""
    p = ArgoPipeline.__new__(ArgoPipeline)
    import logging
    p.logger = logging.getLogger("test.pipeline")
    p.processing_lock = threading.Lock()
    p.stop_signal = threading.Event()
    p.audio = _FakeAudio()
    p.is_speaking = True
    p.tts_finished_at = 0.0
    p.current_state = "SPEAKING"
    p.current_interaction_id = "stuck"
    p.stop_tts = lambda: p.__dict__.setdefault("_tts_stopped", True)
    p.force_state = lambda state, **kw: setattr(p, "current_state", state)
    p.broadcast = lambda *a, **k: None
    return p


def test_hard_reset_frees_a_lock_held_by_another_thread(pipeline):
    """The core guarantee: a stuck turn's lock is broken, not waited on."""
    released = threading.Event()

    def wedged_turn():
        pipeline.processing_lock.acquire()
        released.wait(timeout=5)   # never finishes on its own in this test

    t = threading.Thread(target=wedged_turn, daemon=True)
    t.start()
    time.sleep(0.2)
    assert pipeline.processing_lock.locked(), "setup failed: lock not held"

    result = pipeline.hard_reset("TEST")

    assert result["processing_lock_broken"] is True
    assert not pipeline.processing_lock.locked()
    # A new turn can now take the lock, which is the whole point.
    assert pipeline.processing_lock.acquire(blocking=False)
    pipeline.processing_lock.release()
    released.set()


def test_hard_reset_stops_audio_and_clears_speaking(pipeline):
    pipeline.hard_reset("TEST")
    assert "force_release_audio" in pipeline.audio.calls
    assert "stop_playback" in pipeline.audio.calls
    assert pipeline.is_speaking is False
    assert pipeline.stop_signal.is_set()
    assert pipeline.current_state == "IDLE"


def test_hard_reset_is_safe_when_nothing_is_stuck(pipeline):
    result = pipeline.hard_reset("TEST")
    assert result["ok"] and result["processing_lock_broken"] is False


def test_one_failing_step_does_not_abort_the_rest(pipeline):
    def boom():
        raise RuntimeError("device gone")
    pipeline.audio.stop_playback = boom

    result = pipeline.hard_reset("TEST")

    assert result["ok"]
    assert any("playback_stopped" in f for f in result["failures"])
    # later steps still ran
    assert "flags_cleared" in result["actions"]
    assert pipeline.current_state == "IDLE"


def test_hard_reset_is_idempotent(pipeline):
    pipeline.hard_reset("TEST")
    second = pipeline.hard_reset("TEST")
    assert second["ok"] and second["processing_lock_broken"] is False
