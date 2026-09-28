"""Characterization tests for pipeline identity and confirmation policy."""

import pytest

from core.pipeline import ArgoPipeline


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("My name is Tommy.", "Tommy"),
        ("call me tommy gunn!", "Tommy Gunn"),
        ("you can call me T", None),
        ("I am Sarah", "Sarah"),
        ("today I am tired", None),
        ("my name is " + "x" * 50, None),
    ],
)
def test_extract_name_statement_contract(text, expected):
    pipeline = ArgoPipeline.__new__(ArgoPipeline)

    assert pipeline._extract_name_from_statement(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("yes", True),
        ("Yeah, do it", True),
        ("okay please", True),
        ("correct", True),
        ("yesterday", False),
        ("no", False),
        ("", False),
    ],
)
def test_affirmative_response_contract(text, expected):
    pipeline = ArgoPipeline.__new__(ArgoPipeline)

    assert pipeline._is_affirmative_response(text) is expected

