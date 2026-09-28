import logging
from types import SimpleNamespace

import numpy as np
import pytest

from core.classic_capture import finish_classic_capture


class _Thread:
    created = []

    def __init__(self, *, target, args):
        self.target = target
        self.args = args
        self.started = False
        self.created.append(self)

    def start(self):
        self.started = True


def _world():
    audio = SimpleNamespace(clear_count=0)
    audio.clear_buffers = lambda: setattr(audio, "clear_count", audio.clear_count + 1)
    pipeline = SimpleNamespace(transitions=[])
    pipeline.run_interaction = lambda *_: None
    pipeline.transition_state = lambda state, **kwargs: pipeline.transitions.append((state, kwargs))
    cues = SimpleNamespace(events=[])
    cues.set_capture_active = lambda active: cues.events.append(("capture", active))
    cues.play = lambda name, **kwargs: cues.events.append((name, kwargs))
    events = []
    return audio, pipeline, cues, events


def _finish(buffer, *, mode="classic", overrides=None):
    _Thread.created.clear()
    audio, pipeline, cues, events = _world()
    pending = {"temperature": 0.2} if overrides is None else overrides
    finish_classic_capture(
        buffer,
        audio=audio,
        pipeline=pipeline,
        interaction_id="turn-1",
        voice_mode=mode,
        smooth_voice_mode="smooth",
        next_interaction_overrides=pending,
        sound_cues=cues,
        logger=logging.getLogger("test.classic_capture"),
        event_logger=lambda *args, **kwargs: events.append((args, kwargs)),
        thread_factory=_Thread,
    )
    return audio, pipeline, cues, events, pending


def test_classic_capture_normalizes_and_dispatches_once():
    audio, pipeline, _cues, events, pending = _finish(
        [np.array([[0.1], [-0.2]], dtype=np.float32)]
    )

    assert audio.clear_count == 1
    assert pipeline.transitions == []
    assert events == []
    assert pending == {}
    assert len(_Thread.created) == 1
    worker = _Thread.created[0]
    assert worker.started is True
    captured, interaction_id, replay_mode, overrides = worker.args
    assert captured.ndim == 1
    assert np.max(np.abs(captured)) == pytest.approx(0.9)
    assert (interaction_id, replay_mode, overrides) == (
        "turn-1",
        False,
        {"temperature": 0.2},
    )


def test_smooth_voice_drops_buffer_without_dispatching_or_consuming_overrides():
    audio, pipeline, _cues, events, pending = _finish(
        [np.array([0.4, -0.4], dtype=np.float32)], mode="smooth"
    )

    assert audio.clear_count == 2
    assert _Thread.created == []
    assert pending == {"temperature": 0.2}
    assert pipeline.transitions == [("LISTENING", {"source": "smooth_owns_mic"})]
    assert events[0][0] == ("CLASSIC_TURN_DROPPED reason=smooth_voice_owns_mic",)


def test_quiet_and_empty_captures_return_to_listening_without_dispatch():
    for buffer, source in [([np.zeros(8, dtype=np.float32)], "quiet_reject"), ([], "empty_reject")]:
        audio, pipeline, cues, _events, pending = _finish(buffer)
        assert _Thread.created == []
        assert pending == {"temperature": 0.2}
        assert pipeline.transitions == [("LISTENING", {"source": source})]
        assert audio.clear_count == 1
        assert any(event[0] == "error" for event in cues.events)
