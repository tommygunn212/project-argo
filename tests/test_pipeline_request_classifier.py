from types import SimpleNamespace

import pytest

from core.intent_models import IntentType
from core.pipeline_request_classifier import (
    classify_request_kind,
    classify_request_type,
    has_interrogative_structure,
    is_identity_query,
    meaningful_tokens,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", "UNKNOWN"),
        ("open notepad", "ACTION"),
        ("can you open notepad", "QUESTION"),
        ("what is rag?", "QUESTION"),
        ("audio pipeline", "QUESTION"),
        ("hello", "QUESTION"),
    ],
)
def test_request_kind_rules(text, expected):
    assert classify_request_kind(text) == expected


def test_memory_and_unknown_types_short_circuit_executable_check():
    fail = lambda *_: (_ for _ in ()).throw(AssertionError("must not run"))

    assert classify_request_type("remember this", None, "WRITE_MEMORY", fail) == "WRITE_MEMORY"
    assert classify_request_type("", None, "UNKNOWN", fail) == "UNKNOWN"


@pytest.mark.parametrize(
    ("intent_type", "expected"),
    [
        (IntentType.APP_CONTROL, "ACTION"),
        (IntentType.VOLUME_CONTROL, "ACTION"),
        (IntentType.APP_STATUS, "QUESTION"),
        (IntentType.SYSTEM_HEALTH, "QUESTION"),
    ],
)
def test_intent_type_overrides_request_kind(intent_type, expected):
    intent = SimpleNamespace(intent_type=intent_type)

    assert classify_request_type("request", intent, "QUESTION", lambda *_: False) == expected


def test_music_uses_executable_command_callback():
    intent = SimpleNamespace(intent_type=IntentType.MUSIC)

    assert classify_request_type("play bowie", intent, "QUESTION", lambda *_: True) == "ACTION"
    assert classify_request_type("music", intent, "QUESTION", lambda *_: False) == "QUESTION"


def test_text_shape_helpers_are_deterministic():
    assert has_interrogative_structure("Could this work")
    assert not has_interrogative_structure("This could work")
    assert meaningful_tokens("What is the audio pipeline?") == ["what", "audio", "pipeline"]
    assert is_identity_query("Do you remember my name?")
    assert not is_identity_query("Remember the project name")
