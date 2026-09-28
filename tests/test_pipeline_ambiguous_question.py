"""Boundary cases for terse opaque-question clarification."""

import pytest

from core.pipeline import ArgoPipeline


@pytest.fixture
def pipeline():
    return ArgoPipeline.__new__(ArgoPipeline)


def test_topic_classified_question_bypasses_opaque_term_prompt(pipeline):
    assert (
        pipeline._ambiguous_short_question_prompt(
            "what is mc2", "QUESTION", topic="knowledge"
        )
        is None
    )


def test_non_question_bypasses_opaque_term_prompt(pipeline):
    assert pipeline._ambiguous_short_question_prompt("open mc2", "ACTION") is None


def test_longer_question_is_left_to_normal_answering(pipeline):
    assert (
        pipeline._ambiguous_short_question_prompt(
            "what are abc def ghi", "QUESTION"
        )
        is None
    )


@pytest.mark.parametrize("term", ["api", "cpu", "gpu", "ram"])
def test_known_short_technical_terms_do_not_trigger_clarification(pipeline, term):
    assert (
        pipeline._ambiguous_short_question_prompt(f"what is {term}", "QUESTION")
        is None
    )
