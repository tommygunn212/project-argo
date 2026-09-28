from types import SimpleNamespace

import pytest

from core.intent_parser import IntentType
from core.pipeline_restricted_fallback import block_restricted_llm_fallback


RESTRICTED_INTENTS = [
    IntentType.MUSIC,
    IntentType.MUSIC_STOP,
    IntentType.MUSIC_NEXT,
    IntentType.MUSIC_STATUS,
    IntentType.SYSTEM_HEALTH,
    IntentType.SYSTEM_STATUS,
    IntentType.BLUETOOTH_STATUS,
    IntentType.BLUETOOTH_CONTROL,
    IntentType.AUDIO_ROUTING_STATUS,
    IntentType.AUDIO_ROUTING_CONTROL,
    IntentType.APP_STATUS,
    IntentType.APP_FOCUS_STATUS,
    IntentType.APP_FOCUS_CONTROL,
    IntentType.APP_LAUNCH,
    IntentType.APP_CONTROL,
    IntentType.VOLUME_STATUS,
    IntentType.VOLUME_CONTROL,
    IntentType.TIME_STATUS,
    IntentType.WORLD_TIME,
    IntentType.ARGO_IDENTITY,
    IntentType.ARGO_GOVERNANCE,
    IntentType.WRITE_EMAIL,
    IntentType.WRITE_BLOG,
    IntentType.WRITE_DOCUMENT,
    IntentType.WRITE_NOTE,
    IntentType.EDIT_DRAFT,
    IntentType.LIST_DRAFTS,
    IntentType.READ_DRAFT,
    IntentType.SEND_EMAIL,
    IntentType.SEARCH_DOCS,
    IntentType.EXPORT_DATA,
    IntentType.SMART_HOME_CONTROL,
    IntentType.SMART_HOME_STATUS,
    IntentType.SET_REMINDER,
    IntentType.LIST_REMINDERS,
    IntentType.CANCEL_REMINDER,
    IntentType.CALENDAR_ADD,
    IntentType.CALENDAR_QUERY,
    IntentType.CANCEL_CALENDAR,
    IntentType.VISION_DESCRIBE,
    IntentType.VISION_READ_ERROR,
    IntentType.VISION_QUESTION,
    IntentType.FILE_SEARCH,
    IntentType.FILE_LARGE,
    IntentType.FILE_RECENT,
    IntentType.FILE_INFO,
    IntentType.TASK_PLAN,
]


class FakePipeline:
    def __init__(self):
        self.errors = []
        self.logger = SimpleNamespace(error=lambda message: self.errors.append(message))
        self.deliveries = []

    def _deliver_canonical_response(self, *args):
        self.deliveries.append(args)


@pytest.mark.parametrize("intent_type", RESTRICTED_INTENTS)
def test_every_local_only_intent_is_blocked_before_general_llm(intent_type):
    pipeline = FakePipeline()

    handled = block_restricted_llm_fallback(
        pipeline,
        SimpleNamespace(intent_type=intent_type),
        "raw request",
        "safe request",
        "interaction-1",
        False,
        {"suppress_tts": True},
    )

    assert handled is True
    assert len(pipeline.errors) == 1
    assert len(pipeline.deliveries) == 1
    assert pipeline.deliveries[0][1:] == (
        "interaction-1",
        False,
        {"suppress_tts": True},
    )


@pytest.mark.parametrize("intent", [None, SimpleNamespace(intent_type=IntentType.SYSTEM_INFO)])
def test_non_restricted_intent_falls_through_without_side_effects(intent):
    pipeline = FakePipeline()

    assert not block_restricted_llm_fallback(
        pipeline, intent, "raw", "safe", "interaction-1", False, None
    )
    assert pipeline.errors == []
    assert pipeline.deliveries == []


def test_system_status_uses_the_high_signal_canonical_leak_log():
    pipeline = FakePipeline()

    block_restricted_llm_fallback(
        pipeline,
        SimpleNamespace(intent_type=IntentType.SYSTEM_STATUS),
        "raw",
        "safe",
        "interaction-1",
        False,
        None,
    )

    assert pipeline.errors == ["[CANONICAL LEAK] SYSTEM_STATUS reached LLM – BLOCKING"]
    assert pipeline.deliveries[0][0] == "System status is handled locally. Please ask again."


def test_other_leak_log_uses_sanitized_utterance_and_domain_message():
    pipeline = FakePipeline()

    block_restricted_llm_fallback(
        pipeline,
        SimpleNamespace(intent_type=IntentType.FILE_SEARCH),
        "raw\nrequest",
        "safe request",
        "interaction-1",
        False,
        None,
    )

    assert pipeline.errors == [
        f'[CANONICAL LEAK] intent={IntentType.FILE_SEARCH} text="safe request"'
    ]
    assert pipeline.deliveries[0][0] == "File search failed to route. Say it again."
