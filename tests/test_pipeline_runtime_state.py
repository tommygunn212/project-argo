"""Characterization tests for the classic pipeline runtime-state contract."""

from __future__ import annotations

import logging
import threading
from unittest.mock import Mock

from core.pipeline import ArgoPipeline


def _pipeline(state: str = "IDLE") -> ArgoPipeline:
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.logger = logging.getLogger("test.pipeline.runtime_state")
    pipeline._state_lock = threading.Lock()
    pipeline.current_state = state
    pipeline.illegal_transition = False
    pipeline.illegal_transition_details = None
    pipeline.ALLOWED_TRANSITIONS = {
        "IDLE": {"LISTENING", "THINKING"},
        "LISTENING": {"TRANSCRIBING", "THINKING"},
        "TRANSCRIBING": {"THINKING", "LISTENING", "IDLE"},
        "THINKING": {"SPEAKING", "LISTENING", "IDLE"},
        "SPEAKING": {"LISTENING", "IDLE", "THINKING"},
    }
    pipeline.stop_signal = threading.Event()
    pipeline.timeline_events = []
    pipeline.broadcast = Mock()
    pipeline.sound_cues = Mock()
    pipeline.audio = Mock()
    pipeline.is_speaking = False
    pipeline.current_interaction_id = "active-turn"
    pipeline._edge_tts = None
    pipeline._openai_tts = None
    pipeline._tts_engine = "edge"
    return pipeline


def test_legal_transition_updates_state_broadcasts_and_plays_cue(monkeypatch):
    pipeline = _pipeline()
    log_event = Mock()
    monkeypatch.setattr("core.pipeline.log_event", log_event)

    assert pipeline.transition_state("LISTENING", "turn-1") is True

    assert pipeline.current_state == "LISTENING"
    pipeline.broadcast.assert_called_once_with("status", "LISTENING")
    pipeline.sound_cues.play.assert_called_once_with(
        "listening_start", interaction_id="turn-1", block=False
    )
    assert pipeline.timeline_events[-1]["event"] == "STATE IDLE->LISTENING"
    log_event.assert_called_once_with(
        "STATE IDLE->LISTENING", stage="state", interaction_id="turn-1"
    )


def test_illegal_transition_reports_error_without_mutating_state(monkeypatch):
    pipeline = _pipeline()
    monkeypatch.setattr("core.pipeline.log_event", Mock())

    assert pipeline.transition_state("SPEAKING", "turn-2", source="test") is False

    assert pipeline.current_state == "IDLE"
    assert pipeline.illegal_transition is True
    details = pipeline.illegal_transition_details
    assert details == {
        "from": "IDLE",
        "to": "SPEAKING",
        "allowed": details["allowed"],
        "source": "test",
        "interaction_id": "turn-2",
    }
    assert set(details["allowed"]) == {"LISTENING", "THINKING"}
    assert pipeline.broadcast.call_args_list == [
        (("illegal_transition", pipeline.illegal_transition_details),),
        (("status", "ERROR"),),
        (("log", "ILLEGAL TRANSITION: IDLE → SPEAKING"),),
    ]
    pipeline.sound_cues.play.assert_called_once_with(
        "error", interaction_id="turn-2", block=False
    )


def test_audio_resume_after_interrupt_is_ignored(monkeypatch):
    pipeline = _pipeline()
    pipeline.stop_signal.set()
    monkeypatch.setattr("core.pipeline.log_event", Mock())

    assert pipeline.transition_state("LISTENING", "turn-3", source="audio") is True

    assert pipeline.current_state == "IDLE"
    pipeline.broadcast.assert_not_called()
    pipeline.sound_cues.play.assert_not_called()
    assert pipeline.timeline_events[-1]["event"].endswith("ignored after interrupt")


def test_interrupt_cancels_all_audio_and_forces_requested_state(monkeypatch):
    pipeline = _pipeline("SPEAKING")
    pipeline.is_speaking = True
    pipeline.stop_tts = Mock()
    pipeline.force_state = Mock()
    monkeypatch.setattr("core.pipeline.log_event", Mock())

    pipeline.interrupt_current_response("USER_STOP", target_state="IDLE")

    pipeline.sound_cues.stop_active_cue.assert_called_once_with(
        "USER_STOP", interaction_id="active-turn"
    )
    pipeline.stop_tts.assert_called_once_with()
    pipeline.audio.force_release_audio.assert_called_once_with(
        "USER_STOP", interaction_id="active-turn"
    )
    pipeline.audio.stop_playback.assert_called_once_with()
    pipeline.audio.clear_buffers.assert_called_once_with()
    pipeline.force_state.assert_called_once_with(
        "IDLE", interaction_id="active-turn", source="USER_STOP"
    )
    assert pipeline.stop_signal.is_set()
    assert pipeline.is_speaking is False
    assert pipeline.tts_finished_at > 0


def test_interrupt_can_preserve_buffers_and_state(monkeypatch):
    pipeline = _pipeline("THINKING")
    pipeline.stop_tts = Mock()
    pipeline.force_state = Mock()
    monkeypatch.setattr("core.pipeline.log_event", Mock())

    pipeline.interrupt_current_response(
        "SERVER_STOP", target_state=None, clear_buffers=False
    )

    pipeline.audio.clear_buffers.assert_not_called()
    pipeline.force_state.assert_not_called()

