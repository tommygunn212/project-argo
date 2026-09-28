from types import SimpleNamespace

import pytest

from core.pipeline_canonical_stage import run_canonical_stage


class FakePipeline:
    def __init__(self, classification=(None, set())):
        self.classification = classification
        self._session_flags = {"clarification_asked": True}
        self.stop_signal = SimpleNamespace(is_set=lambda: False)
        self.calls = []
        self.logger = SimpleNamespace(
            info=lambda *args: self.calls.append(("info", args)),
            debug=lambda *args: self.calls.append(("debug", args)),
        )

    def _classify_canonical_topic(self, _text):
        return self.classification

    def _respond_with_system_health(self, *args):
        self.calls.append(("health", args))
        return True

    def _respond_with_argo_governance(self, *args):
        self.calls.append(("governance", args))
        return True

    def _is_convo_recall_request(self, text):
        return text == "recall conversation"

    def _handle_convo_recall(self):
        return "Earlier response"

    def _build_count_response(self, text):
        self.calls.append(("count", (text,)))
        return "One, two, three."

    def broadcast(self, *args):
        self.calls.append(("broadcast", args))

    def _append_convo_ledger(self, *args):
        self.calls.append(("ledger", args))

    def _sanitize_tts_text(self, *args, **kwargs):
        self.calls.append(("sanitize", args, kwargs))
        return args[0]

    def speak(self, *args, **kwargs):
        self.calls.append(("speak", args, kwargs))

    def transition_state(self, *args, **kwargs):
        self.calls.append(("transition", args, kwargs))

    def _record_timeline(self, *args, **kwargs):
        self.calls.append(("timeline", args, kwargs))


def test_no_canonical_match_falls_through_with_empty_state():
    pipeline = FakePipeline()

    result = run_canonical_stage(
        pipeline, "ordinary question", 0.9, "interaction-1", False, None
    )

    assert result.handled is False
    assert result.topic is None
    assert result.matched == set()
    assert pipeline.calls == []


def test_identity_match_deliberately_falls_through_to_persona_llm():
    pipeline = FakePipeline(("ARGO_IDENTITY", {"who are you"}))

    result = run_canonical_stage(
        pipeline, "who are you", 0.9, "interaction-1", False, None
    )

    assert result.handled is False
    assert result.topic is None
    assert result.matched == {"who are you"}


@pytest.mark.parametrize(
    ("topic", "expected_call"),
    [("SYSTEM_HEALTH", "health"), ("ARGO_GOVERNANCE", "governance")],
)
def test_special_canonical_topics_delegate_to_existing_handlers(topic, expected_call):
    pipeline = FakePipeline((topic, {"matched"}))

    result = run_canonical_stage(
        pipeline, "request", 0.9, "interaction-1", False, None
    )

    assert result.handled is True
    assert any(call[0] == expected_call for call in pipeline.calls)


def test_conversation_recall_finishes_with_normal_sanitization():
    pipeline = FakePipeline()

    result = run_canonical_stage(
        pipeline, "recall conversation", 0.9, "interaction-1", False, None
    )

    assert result.handled is True
    assert ("sanitize", ("Earlier response",), {}) in pipeline.calls
    assert ("ledger", ("argo", "Earlier response")) in pipeline.calls


def test_low_confidence_single_keyword_match_defers_to_llm():
    pipeline = FakePipeline(("ARCHITECTURE", {"architecture"}))

    result = run_canonical_stage(
        pipeline, "architecture", 0.4, "interaction-1", False, None
    )

    assert result.handled is False
    assert result.topic is None
    assert not any(call[0] == "broadcast" for call in pipeline.calls)


def test_count_uses_deterministic_confidence_bypass():
    pipeline = FakePipeline(("COUNT", {"count"}))

    result = run_canonical_stage(
        pipeline, "count to three", 0.2, "interaction-1", False, None
    )

    assert result.handled is True
    assert (
        "sanitize",
        ("One, two, three.",),
        {"enforce_confidence": False, "deterministic": True},
    ) in pipeline.calls


def test_regular_canonical_answer_is_deterministic_and_clears_clarification(monkeypatch):
    pipeline = FakePipeline(("ARCHITECTURE", {"system architecture"}))
    monkeypatch.setattr(
        "core.pipeline_canonical_stage.get_canonical_answer",
        lambda topic: f"answer:{topic}",
    )

    result = run_canonical_stage(
        pipeline, "system architecture", 0.9, "interaction-1", False, None
    )

    assert result.handled is True
    assert pipeline._session_flags["clarification_asked"] is False
    assert ("ledger", ("argo", "answer:ARCHITECTURE")) in pipeline.calls
