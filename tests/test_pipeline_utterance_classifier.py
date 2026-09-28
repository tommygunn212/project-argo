"""Behavior tests for non-propositional utterance classification."""

import pytest

from core.pipeline import ArgoPipeline


@pytest.fixture
def pipeline():
    return ArgoPipeline.__new__(ArgoPipeline)


@pytest.mark.parametrize(
    "text",
    ["", "huh?", "what", "umm", "I don't understand", "it seems like human"],
)
def test_explicit_non_propositional_fragments_are_detected(pipeline, text):
    assert pipeline._is_non_propositional_utterance(text, "QUESTION") is True


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("open calculator", "ACTION"),
        ("give me an example", "STATEMENT"),
        ("my name is Tommy", "STATEMENT"),
        ("the sky looks clear", "STATEMENT"),
    ],
)
def test_actionable_or_meaningful_text_is_not_rejected(pipeline, text, kind):
    assert pipeline._is_non_propositional_utterance(text, kind) is False
