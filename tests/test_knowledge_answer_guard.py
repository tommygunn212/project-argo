from core.knowledge_answer_guard import enforce_knowledge_answer
from types import SimpleNamespace
from unittest.mock import Mock
import threading


def enforce(response, **overrides):
    values = {
        "initial_response": response,
        "user_text": "why does it cool",
        "intent_type": "knowledge_physics",
        "confidence": 1.0,
        "must_pass_phrases": None,
        "retry": lambda schema, model: "Principle: heat transfer\nExplanation: energy moves.",
        "default_model": "default",
    }
    values.update(overrides)
    return enforce_knowledge_answer(**values)


def test_valid_initial_answer_does_not_retry():
    calls = []
    result = enforce(
        "Principle: heat transfer\nExplanation: energy moves.",
        retry=lambda *args: calls.append(args),
    )
    assert result.outcome == "initial_pass"
    assert calls == []


def test_invalid_answer_retries_with_strict_model():
    calls = []
    result = enforce(
        "It gets cold.",
        retry=lambda schema, model: calls.append((schema, model)) or "Principle: energy\nExplanation: heat moves.",
    )
    assert result.outcome == "retry_pass"
    assert calls[0][1] == "gpt-4.1"


def test_must_pass_failure_uses_auditable_fallback():
    result = enforce(
        "bad",
        user_text="required phrase",
        must_pass_phrases={"Required Phrase": "knowledge_physics"},
        retry=lambda *args: "still bad",
    )
    assert result.outcome == "must_pass_fallback"
    assert "Heat transfer and thermodynamics" in result.text
    assert result.text.endswith("[system_generated: true]")


def test_low_confidence_and_nonknowledge_answers_are_untouched():
    assert enforce("raw", confidence=0.94).text == "raw"
    assert enforce("raw", intent_type="conversation").text == "raw"


def test_failed_optional_answer_is_returned_with_warning():
    result = enforce("bad", retry=lambda *args: "also bad")
    assert result.outcome == "retry_weak"
    assert result.text.startswith("also bad")
    assert "Answer may be incomplete" in result.text


def test_pipeline_facade_streams_retry_through_the_extracted_guard():
    from core.pipeline import ArgoPipeline

    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.llm_enabled = True
    pipeline.logger = Mock()
    pipeline.stop_signal = threading.Event()
    pipeline._conversation_buffer = SimpleNamespace(as_messages=lambda: [])
    pipeline._llm_router = SimpleNamespace(last_model="default")
    pipeline.llm_model_name = "default"
    pipeline._resolve_personality_mode = lambda: "plain"
    pipeline._is_serious = lambda text: False
    pipeline._build_llm_prompt = lambda *args, **kwargs: args[0]
    pipeline._get_system_message = lambda *args: "system"
    pipeline._strip_prompt_artifacts = lambda text: text
    pipeline._record_timeline = Mock()
    pipeline.broadcast = Mock()
    responses = iter([
        ["unstructured"],
        ["Principle: heat transfer\nExplanation: energy moves."],
    ])
    models = []

    def stream(**kwargs):
        models.append(kwargs.get("model_override"))
        return next(responses)

    pipeline._stream_llm_text = stream

    result = pipeline.generate_response(
        "why does it cool",
        intent_type="knowledge_physics",
        confidence=1.0,
    )

    assert result.startswith("Principle: heat transfer")
    assert models == [None, "gpt-4.1"]
