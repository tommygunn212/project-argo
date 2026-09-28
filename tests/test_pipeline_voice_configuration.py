"""Characterization tests for classic pipeline voice configuration."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import Mock

from core.pipeline import ArgoPipeline


def _pipeline() -> ArgoPipeline:
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.logger = logging.getLogger("test.pipeline.voice_configuration")
    pipeline.broadcast = Mock()
    pipeline.openai_voices = {"nova": "nova", "alloy": "alloy"}
    pipeline.voices = {"ryan": "en-GB-RyanNeural"}
    pipeline.current_voice_key = "ryan"
    pipeline._tts_engine = "edge"
    pipeline._tts_model = "tts-1"
    pipeline._openai_tts = Mock()
    pipeline._edge_tts = SimpleNamespace(voice="old-edge-voice")
    return pipeline


def test_set_voice_selects_openai_and_updates_live_client():
    pipeline = _pipeline()

    assert pipeline.set_voice("nova") is True

    assert pipeline.current_voice_key == "nova"
    assert pipeline._tts_engine == "openai"
    pipeline._openai_tts.set_voice.assert_called_once_with("nova")
    pipeline.broadcast.assert_called_once_with(
        "log", "System: Voice switched to OpenAI NOVA"
    )


def test_set_voice_selects_edge_and_updates_live_client():
    pipeline = _pipeline()

    assert pipeline.set_voice("ryan") is True

    assert pipeline.current_voice_key == "ryan"
    assert pipeline._tts_engine == "edge"
    assert pipeline._edge_tts.voice == "en-GB-RyanNeural"
    pipeline.broadcast.assert_called_once_with(
        "log", "System: Voice profile switched to RYAN"
    )


def test_unknown_voice_preserves_configuration():
    pipeline = _pipeline()

    assert pipeline.set_voice("missing") is False

    assert pipeline.current_voice_key == "ryan"
    assert pipeline._tts_engine == "edge"
    pipeline._openai_tts.set_voice.assert_not_called()
    pipeline.broadcast.assert_not_called()


def test_set_tts_model_reinitializes_openai_client_on_change():
    pipeline = _pipeline()

    assert pipeline.set_tts_model("gpt-4o-mini-tts") is True

    assert pipeline._tts_model == "gpt-4o-mini-tts"
    assert pipeline._openai_tts is None
    pipeline.broadcast.assert_called_once_with(
        "log", "System: TTS model switched to gpt-4o-mini-tts"
    )


def test_same_or_invalid_tts_model_does_not_reset_client():
    pipeline = _pipeline()
    original_client = pipeline._openai_tts

    assert pipeline.set_tts_model("tts-1") is True
    assert pipeline.set_tts_model("made-up-model") is False

    assert pipeline._openai_tts is original_client
    pipeline.broadcast.assert_not_called()

