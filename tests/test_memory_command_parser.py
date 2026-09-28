import pytest

from core.memory_command_parser import parse_memory_write


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("my name is tommy", {"type": "FACT", "key": "user.name", "value": "Tommy", "display": "My name is Tommy", "implicit": True}),
        ("call me t-bone", {"type": "FACT", "key": "user.name", "value": "T-Bone", "display": "Call me T-Bone", "implicit": True}),
        ("I prefer short answers.", {"type": "PREFERENCE", "key": "user.preference", "value": "short answers", "display": "I prefer short answers", "implicit": True}),
        ("remember that I like jazz", {"type": "FACT", "key": "user.likes", "value": "jazz", "display": "I like jazz"}),
        ("remember project database is postgres", {"type": "PROJECT", "key": "project database", "value": "postgres", "display": "project database is postgres"}),
        ("remember preference: concise", {"type": "PREFERENCE", "key": "preference", "value": "concise", "display": "preference: concise"}),
        ("remember everything", {"reject": "bulk"}),
        ("remember", {"type": "FACT", "key": None, "value": None}),
        ("ordinary conversation", None),
    ],
)
def test_parse_memory_write_contract(text, expected):
    assert parse_memory_write(text) == expected
