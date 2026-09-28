"""Behavior tests for classic canonical response delivery."""

import threading
from unittest.mock import Mock

from core.pipeline import ArgoPipeline
from personas import ResponseType


def _pipeline():
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline._resolve_personality_mode = Mock(return_value="plain")
    pipeline._personal_mode_min_confidence = 0.5
    pipeline.logger = Mock()
    pipeline.broadcast = Mock()
    pipeline.stop_signal = threading.Event()
    pipeline._sanitize_tts_text = Mock(return_value="spoken response")
    pipeline.runtime_overrides = {"tts_enabled": True}
    pipeline._pending_barge_in_suppression = None
    pipeline._edge_tts = None
    pipeline.speak = Mock()
    pipeline.transition_state = Mock()
    pipeline._record_timeline = Mock()
    return pipeline


def test_delivery_applies_persona_broadcasts_speaks_and_finishes(monkeypatch):
    pipeline = _pipeline()
    apply_persona = Mock(return_value="persona response")
    monkeypatch.setattr("core.pipeline.apply_persona", apply_persona)

    result = pipeline._deliver_canonical_response(
        "raw response",
        "turn-1",
        False,
        None,
        response_type=ResponseType.CLARIFICATION,
    )

    assert result is True
    apply_persona.assert_called_once_with(
        "raw response", ResponseType.CLARIFICATION, "plain"
    )
    pipeline.broadcast.assert_called_once_with("log", "Argo: persona response")
    pipeline._sanitize_tts_text.assert_called_once_with(
        "persona response", enforce_confidence=True, deterministic=True
    )
    pipeline.speak.assert_called_once_with(
        "spoken response", interaction_id="turn-1"
    )
    pipeline.transition_state.assert_called_once_with(
        "LISTENING", interaction_id="turn-1", source="audio"
    )
    pipeline._record_timeline.assert_called_once_with(
        "INTERACTION_END", stage="pipeline", interaction_id="turn-1"
    )


def test_replay_and_stop_each_skip_speech_but_finish(monkeypatch):
    monkeypatch.setattr("core.pipeline.apply_persona", lambda message, *_: message)

    replay = _pipeline()
    replay._deliver_canonical_response("response", "replay", True, None)
    replay._sanitize_tts_text.assert_not_called()
    replay.speak.assert_not_called()
    replay.transition_state.assert_called_once()

    stopped = _pipeline()
    stopped.stop_signal.set()
    stopped._deliver_canonical_response("response", "stopped", False, None)
    stopped._sanitize_tts_text.assert_not_called()
    stopped.speak.assert_not_called()
    stopped.transition_state.assert_called_once()


def test_force_tts_overrides_both_suppression_and_runtime_disable(monkeypatch):
    monkeypatch.setattr("core.pipeline.apply_persona", lambda message, *_: message)
    pipeline = _pipeline()
    pipeline.runtime_overrides["tts_enabled"] = False

    pipeline._deliver_canonical_response(
        "response",
        "turn-2",
        False,
        {"suppress_tts": True},
        force_tts=True,
    )

    pipeline.speak.assert_called_once_with(
        "spoken response", interaction_id="turn-2"
    )


def test_suppression_override_skips_speech(monkeypatch):
    monkeypatch.setattr("core.pipeline.apply_persona", lambda message, *_: message)
    pipeline = _pipeline()

    pipeline._deliver_canonical_response(
        "response", "turn-3", False, {"suppress_tts": True}
    )

    pipeline.speak.assert_not_called()
    pipeline.logger.info.assert_any_call(
        "[TTS] Suppressed for next interaction override"
    )


def test_delivery_sets_barge_suppression_on_pipeline_and_live_edge_tts(monkeypatch):
    monkeypatch.setattr("core.pipeline.apply_persona", lambda message, *_: message)
    pipeline = _pipeline()
    pipeline._edge_tts = Mock()

    pipeline._deliver_canonical_response(
        "response",
        "turn-4",
        False,
        None,
        suppress_barge_in_seconds=1.25,
    )

    assert pipeline._pending_barge_in_suppression == 1.25
    pipeline._edge_tts.suppress_interrupt.assert_called_once_with(1.25)


def test_deterministic_low_confidence_delivery_records_bypass_reason(monkeypatch):
    monkeypatch.setattr("core.pipeline.apply_persona", lambda message, *_: message)
    pipeline = _pipeline()

    pipeline._deliver_canonical_response(
        "response",
        "turn-5",
        False,
        None,
        stt_conf=0.2,
        intent_type="system_status",
    )

    assert any(
        "DETERMINISTIC_CONFIDENCE_BYPASS" in call.args[0]
        and "confidence=0.20" in call.args[0]
        and "intent=system_status" in call.args[0]
        for call in pipeline.logger.info.call_args_list
    )
