"""Behavior and ownership tests for classic non-streaming speech."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

from core.pipeline import ArgoPipeline


def _pipeline():
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.runtime_overrides = {"tts_enabled": True}
    pipeline.logger = Mock()
    pipeline.current_voice_key = "aria"
    pipeline._tts_engine = "edge"
    pipeline.current_state = "LISTENING"
    pipeline.transition_state = Mock()
    pipeline.stop_signal = threading.Event()
    pipeline.is_speaking = False
    pipeline._record_timeline = Mock()
    pipeline.audio = SimpleNamespace(
        acquire_audio=Mock(),
        release_audio=Mock(),
        _output_device_index=4,
    )
    pipeline._edge_tts = Mock()
    pipeline._openai_tts = None
    pipeline.voices = {"aria": "en-US-AriaNeural"}
    pipeline.openai_voices = {"aria": "nova"}
    pipeline._tts_model = "tts-1"
    pipeline._TTS_INSTRUCTIONS = "natural"
    pipeline._pending_barge_in_suppression = None
    pipeline.broadcast = Mock()
    pipeline._play_sound_cue = Mock()
    pipeline.tts_finished_at = 0.0
    return pipeline


def test_disabled_speech_has_no_state_or_audio_side_effects():
    pipeline = _pipeline()
    pipeline.runtime_overrides["tts_enabled"] = False

    pipeline.speak("hello", interaction_id="turn-1")

    pipeline.transition_state.assert_not_called()
    pipeline.audio.acquire_audio.assert_not_called()
    pipeline._edge_tts.speak.assert_not_called()


def test_edge_speech_acquires_plays_and_releases_audio():
    pipeline = _pipeline()

    pipeline.speak("hello", interaction_id="turn-2")

    pipeline.audio.acquire_audio.assert_called_once_with(
        "TTS", interaction_id="turn-2"
    )
    pipeline._edge_tts.speak.assert_called_once_with("hello")
    pipeline.audio.release_audio.assert_called_once_with(
        "TTS", interaction_id="turn-2"
    )
    assert pipeline.is_speaking is False
    pipeline._record_timeline.assert_any_call(
        "TTS_DONE", stage="tts", interaction_id="turn-2"
    )


def test_contested_speech_does_not_release_unowned_audio():
    pipeline = _pipeline()
    pipeline.audio.acquire_audio.side_effect = RuntimeError("owned elsewhere")

    pipeline.speak("hello", interaction_id="turn-3")

    pipeline._edge_tts.speak.assert_not_called()
    pipeline.audio.release_audio.assert_not_called()
    pipeline._play_sound_cue.assert_called_once_with(
        "error", interaction_id="turn-3"
    )
    assert pipeline.is_speaking is False
