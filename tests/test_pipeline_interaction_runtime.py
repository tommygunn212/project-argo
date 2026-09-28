"""Characterization tests for classic pipeline interaction ownership."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from core.pipeline import ArgoPipeline


def _pipeline():
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.processing_lock = threading.Lock()
    pipeline.stop_signal = threading.Event()
    pipeline.timeline_events = []
    pipeline.current_interaction_id = ""
    pipeline.current_state = "LISTENING"
    pipeline.is_speaking = False
    pipeline.logger = Mock()
    pipeline.broadcast = Mock()
    pipeline._record_timeline = Mock()
    pipeline.transition_state = Mock()
    pipeline._recover_failed_turn = Mock()
    pipeline.audio = SimpleNamespace(acquire_audio=Mock(), release_audio=Mock())
    pipeline.transcribe = Mock(return_value="hello")
    pipeline._last_stt_metrics = {"confidence": 0.9}
    pipeline._normalize_music_command_text = Mock(side_effect=lambda text: text)
    pipeline._is_low_confidence_stt_prompt_echo = Mock(return_value=False)
    pipeline._conversation_buffer = SimpleNamespace(add=Mock())
    pipeline._broadcast_turn_info = Mock()
    pipeline._append_convo_ledger = Mock()
    pipeline.handle_user_text = Mock()
    return pipeline


def test_busy_interaction_does_not_disturb_active_turn():
    pipeline = _pipeline()
    pipeline.processing_lock.acquire()

    pipeline.run_interaction(np.zeros(16), interaction_id="new")

    pipeline.audio.acquire_audio.assert_not_called()
    pipeline._recover_failed_turn.assert_not_called()
    assert pipeline.processing_lock.locked()
    pipeline.processing_lock.release()


def test_contested_audio_does_not_release_unowned_audio():
    pipeline = _pipeline()
    pipeline.audio.acquire_audio.side_effect = RuntimeError("owned elsewhere")

    pipeline.run_interaction(np.zeros(16), interaction_id="turn-1")

    pipeline.audio.release_audio.assert_not_called()
    pipeline.transcribe.assert_not_called()
    pipeline._record_timeline.assert_any_call(
        "STT_AUDIO_CONTESTED", stage="audio", interaction_id="turn-1"
    )
    pipeline._recover_failed_turn.assert_called_once_with("turn-1")
    assert not pipeline.processing_lock.locked()


def test_low_confidence_prompt_echo_never_reaches_text_router():
    pipeline = _pipeline()
    pipeline.transcribe.return_value = "Argo home assistant"
    pipeline._last_stt_metrics = {"confidence": 0.2}
    pipeline._is_low_confidence_stt_prompt_echo.return_value = True

    pipeline.run_interaction(np.zeros(16), interaction_id="turn-2")

    pipeline.audio.release_audio.assert_called_once_with(
        "STT", interaction_id="turn-2"
    )
    pipeline.handle_user_text.assert_not_called()
    pipeline.transition_state.assert_any_call(
        "LISTENING", interaction_id="turn-2", source="audio"
    )
    pipeline._record_timeline.assert_any_call(
        "STT_PROMPT_ECHO_IGNORED", stage="stt", interaction_id="turn-2"
    )
