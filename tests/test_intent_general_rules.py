import pytest

from core.intent_models import IntentType
from core.intent_rules.general import (
    parse_development_or_tech,
    parse_generic_utterance,
    parse_performance_intent,
)


def test_development_rule_precedes_tech_rule():
    result = parse_development_or_tech(
        "debug the python service",
        "debug the python service",
        False,
        {"debug"},
        {"python"},
    )

    assert result.intent_type is IntentType.DEVELOP
    assert result.confidence == 0.98


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (("can", "you", "count"), IntentType.COUNT),
        (("please", "sing"), IntentType.COMMAND),
        (("ordinary", "words"), None),
    ],
)
def test_performance_rules_preserve_count_priority(tokens, expected):
    result = parse_performance_intent("request", tokens, False)

    assert (result.intent_type if result else None) is expected


@pytest.mark.parametrize(
    ("raw_text", "first_word", "expected", "confidence"),
    [
        ("hello?", "hello", IntentType.QUESTION, 1.0),
        ("why now", "why", IntentType.QUESTION, 0.85),
        ("hello there", "hello", IntentType.GREETING, 0.95),
        ("open it", "open", IntentType.COMMAND, 0.75),
        ("something else", "something", IntentType.UNKNOWN, 0.1),
    ],
)
def test_generic_rule_order(raw_text, first_word, expected, confidence):
    result = parse_generic_utterance(
        raw_text,
        first_word,
        True,
        {"why"},
        {"hello"},
        {"open"},
    )

    assert result.intent_type is expected
    assert result.confidence == confidence
    assert result.serious_mode is True
