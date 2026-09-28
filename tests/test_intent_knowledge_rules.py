import pytest

from core.intent_models import IntentType
from core.intent_rules.knowledge import parse_knowledge_intent


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("why does coffee cool", IntentType.KNOWLEDGE_PHYSICS),
        ("explain thermodynamics", IntentType.KNOWLEDGE_PHYSICS),
        ("is bitcoin money", IntentType.KNOWLEDGE_FINANCE),
        ("explain a bond", IntentType.KNOWLEDGE_FINANCE),
        ("what time is it", IntentType.KNOWLEDGE_TIME_SYSTEM),
        ("show cpu usage", IntentType.KNOWLEDGE_TIME_SYSTEM),
    ],
)
def test_specific_knowledge_domains_are_deterministic(text, expected):
    result = parse_knowledge_intent(text, text, False)

    assert result.intent_type is expected
    assert result.confidence == 1.0


def test_unrelated_question_falls_through_to_generic_parser_rules():
    assert parse_knowledge_intent("capital of france", "capital of france", False) is None


def test_serious_mode_is_preserved_on_knowledge_intent():
    result = parse_knowledge_intent("heat emergency", "heat emergency", True)

    assert result.serious_mode is True
