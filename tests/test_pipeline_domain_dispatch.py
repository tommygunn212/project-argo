from types import SimpleNamespace

import pytest

from core.intent_parser import IntentType
from core.pipeline_domain_dispatch import _DOMAIN_HANDLERS, dispatch_domain_intent


class RecordingPipeline:
    def __init__(self, result=True):
        self.calls = []
        self.result = result

    def __getattr__(self, name):
        if name not in _DOMAIN_HANDLERS.values():
            raise AttributeError(name)

        def handler(*args):
            self.calls.append((name, args))
            return self.result

        return handler


@pytest.mark.parametrize(("intent_type", "handler_name"), _DOMAIN_HANDLERS.items())
def test_each_domain_intent_routes_to_its_only_handler(intent_type, handler_name):
    pipeline = RecordingPipeline()
    intent = SimpleNamespace(intent_type=intent_type)

    handled = dispatch_domain_intent(
        pipeline, intent, "request", "interaction-1", False, {"suppress_tts": True}
    )

    assert handled is True
    assert pipeline.calls == [
        (
            handler_name,
            (intent, "request", "interaction-1", False, {"suppress_tts": True}),
        )
    ]


@pytest.mark.parametrize("intent", [None, SimpleNamespace(intent_type=IntentType.MUSIC)])
def test_non_domain_intent_falls_through_without_calling_a_handler(intent):
    pipeline = RecordingPipeline()

    assert dispatch_domain_intent(pipeline, intent, "request", "interaction-1", False, None) is False
    assert pipeline.calls == []


def test_handler_can_decline_and_allow_pipeline_fallthrough():
    pipeline = RecordingPipeline(result=False)
    intent = SimpleNamespace(intent_type=IntentType.FILE_SEARCH)

    assert dispatch_domain_intent(pipeline, intent, "request", "interaction-1", False, None) is False
    assert len(pipeline.calls) == 1
