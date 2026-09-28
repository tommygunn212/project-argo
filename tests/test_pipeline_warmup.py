"""Characterization tests for classic pipeline startup orchestration."""

from unittest.mock import Mock

import pytest

from core.pipeline import ArgoPipeline


def _pipeline(config=None):
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.logger = Mock()
    pipeline.broadcast = Mock()
    pipeline._config = config or {}
    pipeline._stt_prompt_profile = "home-assistant"
    pipeline._TTS_INSTRUCTIONS = "speak naturally"
    pipeline.audio = Mock(_output_device_index=7)
    pipeline.runtime_overrides = {}
    pipeline._tts_min_confidence = 0.8
    pipeline._personal_mode_min_confidence = 0.5
    pipeline.llm_enabled = True
    pipeline._llm_router = Mock(primary_model_name="llama-test")
    pipeline._openai_tts = None
    return pipeline


def test_warmup_initializes_stt_llm_and_statuses_in_order(monkeypatch):
    pipeline = _pipeline(
        {
            "speech_to_text": {
                "engine": "faster",
                "model": "small",
                "device": "cpu",
            },
            "text_to_speech": {"engine": "edge"},
        }
    )
    manager = Mock(model=object())
    manager_factory = Mock(return_value=manager)
    manager_factory.SUPPORTED_ENGINES = ("openai", "faster")
    dependency_check = Mock()
    monkeypatch.setattr("core.pipeline.STTEngineManager", manager_factory)
    monkeypatch.setattr("core.pipeline.verify_engine_dependencies", dependency_check)

    pipeline.warmup()

    dependency_check.assert_called_once_with("faster")
    manager_factory.assert_called_once_with(
        engine="faster", model_size="small", device="cpu"
    )
    assert pipeline.stt_engine_manager is manager
    assert pipeline.stt_engine == "faster"
    assert pipeline.stt_model_name == "small"
    assert pipeline._tts_engine == "edge"
    pipeline._llm_router.warmup.assert_called_once_with()
    assert pipeline.llm_model_name == "llama-test"
    assert pipeline.broadcast.call_args_list == [
        (("status", "WARMING_UP"),),
        (("status", "READY"),),
    ]


def test_warmup_stt_failure_never_broadcasts_ready(monkeypatch):
    pipeline = _pipeline()
    monkeypatch.setattr(
        "core.pipeline.verify_engine_dependencies",
        Mock(side_effect=RuntimeError("missing engine")),
    )

    with pytest.raises(RuntimeError, match="missing engine"):
        pipeline.warmup()

    assert pipeline.broadcast.call_args_list == [
        (("status", "WARMING_UP"),)
    ]


def test_warmup_openai_tts_failure_falls_back_to_edge(monkeypatch):
    pipeline = _pipeline(
        {
            "speech_to_text": {},
            "text_to_speech": {
                "engine": "openai",
                "voice": "nova",
                "model": "tts-test",
            },
        }
    )
    monkeypatch.setattr("core.pipeline.verify_engine_dependencies", Mock())
    manager_factory = Mock(return_value=Mock())
    manager_factory.SUPPORTED_ENGINES = ("openai", "faster")
    monkeypatch.setattr("core.pipeline.STTEngineManager", manager_factory)
    monkeypatch.setattr(
        "core.openai_tts.OpenAIRealtimeTTS",
        Mock(side_effect=RuntimeError("no credentials")),
    )

    pipeline.warmup()

    assert pipeline._tts_engine == "edge"
    pipeline.logger.warning.assert_any_call(
        "[TTS] OpenAI TTS init failed, falling back to Edge: no credentials"
    )
    pipeline.broadcast.assert_called_with("status", "READY")


def test_warmup_personal_mode_removes_confidence_floors(monkeypatch):
    pipeline = _pipeline()
    pipeline.runtime_overrides["personal_mode"] = True
    pipeline.llm_enabled = False
    monkeypatch.setattr("core.pipeline.verify_engine_dependencies", Mock())
    manager_factory = Mock(return_value=Mock())
    manager_factory.SUPPORTED_ENGINES = ("openai", "faster")
    monkeypatch.setattr("core.pipeline.STTEngineManager", manager_factory)

    pipeline.warmup()

    assert pipeline._tts_min_confidence == 0.0
    assert pipeline._personal_mode_min_confidence == 0.0
