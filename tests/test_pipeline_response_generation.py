import threading
from types import SimpleNamespace
from unittest.mock import Mock

from core.pipeline_response_generation import PipelineResponseGenerationService


def _host(*, enabled=True):
    return SimpleNamespace(
        llm_enabled=enabled,
        llm_model_name="fallback-model",
        logger=Mock(),
        stop_signal=threading.Event(),
        _conversation_buffer=SimpleNamespace(as_messages=lambda: []),
        _llm_router=SimpleNamespace(last_model="default-model"),
        _resolve_personality_mode=Mock(return_value="plain"),
        _is_serious=Mock(return_value=False),
        _build_llm_prompt=Mock(return_value="prompt"),
        _get_system_message=Mock(return_value="system"),
        _stream_llm_text=Mock(return_value=iter(["answer"])),
        _strip_prompt_artifacts=Mock(side_effect=lambda text: text),
        _record_timeline=Mock(),
        broadcast=Mock(),
    )


def test_disabled_llm_returns_without_building_prompt():
    host = _host(enabled=False)

    result = PipelineResponseGenerationService(host).generate("hello")

    assert result == ""
    host._build_llm_prompt.assert_not_called()
    host._stream_llm_text.assert_not_called()


def test_stream_failure_returns_error_and_records_timeline():
    host = _host()
    host._stream_llm_text.side_effect = RuntimeError("offline")

    result = PipelineResponseGenerationService(host).generate(
        "hello", interaction_id="turn-1"
    )

    assert result == "[Error connecting to LLM]"
    host._record_timeline.assert_any_call(
        "LLM_ERROR", stage="llm", interaction_id="turn-1"
    )
    host.broadcast.assert_not_called()
