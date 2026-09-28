from types import SimpleNamespace

import pytest

from core.intent_parser import IntentType
from core.pipeline_special_dispatch import dispatch_special_intent


class FakePipeline:
    def __init__(self):
        self.calls = []
        self.stop_signal = SimpleNamespace(is_set=lambda: False)
        self.logger = SimpleNamespace(info=lambda *args: self.calls.append(("log", args)))

    def _respond_with_silence_override(self, *args):
        self.calls.append(("silence", args))
        return True

    def _respond_with_argo_governance(self, *args):
        self.calls.append(("governance", args))
        return True

    def _respond_with_system_health(self, *args):
        self.calls.append(("health", args))
        return True

    def _respond_with_self_diagnostics(self, *args):
        self.calls.append(("diagnostics", args))
        return True

    def _build_count_response(self, text):
        self.calls.append(("build_count", (text,)))
        return "counted"

    def broadcast(self, *args):
        self.calls.append(("broadcast", args))

    def _sanitize_tts_text(self, *args, **kwargs):
        self.calls.append(("sanitize", args, kwargs))
        return args[0]

    def speak(self, *args, **kwargs):
        self.calls.append(("speak", args, kwargs))

    def transition_state(self, *args, **kwargs):
        self.calls.append(("transition", args, kwargs))

    def _record_timeline(self, *args, **kwargs):
        self.calls.append(("timeline", args, kwargs))


@pytest.mark.parametrize(
    ("intent_type", "expected_call"),
    [
        (IntentType.SILENCE_OVERRIDE, "silence"),
        (IntentType.ARGO_GOVERNANCE, "governance"),
        (IntentType.SYSTEM_HEALTH, "health"),
        (IntentType.SYSTEM_STATUS, "health"),
        (IntentType.SELF_DIAGNOSTICS, "diagnostics"),
    ],
)
def test_special_intent_routes_to_expected_handler(intent_type, expected_call):
    pipeline = FakePipeline()
    parsed_intent = SimpleNamespace(intent_type=intent_type)

    assert dispatch_special_intent(
        pipeline, parsed_intent, "request", "interaction-1", False, None
    ) is True
    assert [call[0] for call in pipeline.calls] == [expected_call]


def test_identity_is_logged_but_falls_through_to_persona_llm():
    pipeline = FakePipeline()

    assert dispatch_special_intent(
        pipeline,
        SimpleNamespace(intent_type=IntentType.ARGO_IDENTITY),
        "who are you",
        "interaction-1",
        False,
        None,
    ) is False
    assert pipeline.calls[0][0] == "log"


@pytest.mark.parametrize("intent", [None, SimpleNamespace(intent_type=IntentType.MUSIC)])
def test_unrelated_intent_falls_through(intent):
    pipeline = FakePipeline()

    assert dispatch_special_intent(
        pipeline, intent, "request", "interaction-1", False, None
    ) is False
    assert pipeline.calls == []


def test_count_response_preserves_confidence_bypass_and_completion():
    pipeline = FakePipeline()

    assert dispatch_special_intent(
        pipeline,
        SimpleNamespace(intent_type=IntentType.COUNT),
        "count to three",
        "interaction-1",
        False,
        None,
    ) is True

    assert ("sanitize", ("counted",), {"enforce_confidence": False}) in pipeline.calls
    assert any(call[0] == "speak" for call in pipeline.calls)
    assert any(call[0] == "transition" for call in pipeline.calls)
    assert any(call[0] == "timeline" for call in pipeline.calls)
