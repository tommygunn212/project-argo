from types import SimpleNamespace

import pytest

from core.intent_parser import IntentType
from core.pipeline_platform_dispatch import (
    _Arguments,
    _PLATFORM_HANDLERS,
    dispatch_platform_intent,
)


class RecordingPipeline:
    def __init__(self, result=True):
        self.calls = []
        self.result = result

    def __getattr__(self, name):
        if name not in {route[0] for route in _PLATFORM_HANDLERS.values()}:
            raise AttributeError(name)

        def handler(*args):
            self.calls.append((name, args))
            return self.result

        return handler


@pytest.mark.parametrize(("intent_type", "route"), _PLATFORM_HANDLERS.items())
def test_each_platform_intent_uses_the_original_handler_signature(intent_type, route):
    pipeline = RecordingPipeline()
    intent = SimpleNamespace(intent_type=intent_type)
    handler_name, argument_shape = route
    trailing = ("interaction-1", False, {"suppress_tts": True})
    expected_prefix = {
        _Arguments.USER_TEXT: ("request",),
        _Arguments.INTENT: (intent,),
        _Arguments.INTENT_TEXT_CONFIDENCE: (intent, "request", 0.75),
        _Arguments.INTERACTION: (),
    }[argument_shape]

    handled = dispatch_platform_intent(
        pipeline,
        intent,
        "request",
        0.75,
        "interaction-1",
        False,
        {"suppress_tts": True},
    )

    assert handled is True
    assert pipeline.calls == [(handler_name, (*expected_prefix, *trailing))]


@pytest.mark.parametrize("intent", [None, SimpleNamespace(intent_type=IntentType.MUSIC)])
def test_non_platform_intent_falls_through_without_handler_call(intent):
    pipeline = RecordingPipeline()

    handled = dispatch_platform_intent(
        pipeline, intent, "request", 0.75, "interaction-1", False, None
    )

    assert handled is False
    assert pipeline.calls == []


def test_handler_can_decline_and_allow_pipeline_fallthrough():
    pipeline = RecordingPipeline(result=False)
    intent = SimpleNamespace(intent_type=IntentType.APP_CONTROL)

    assert not dispatch_platform_intent(
        pipeline, intent, "request", 0.75, "interaction-1", False, None
    )
    assert len(pipeline.calls) == 1
