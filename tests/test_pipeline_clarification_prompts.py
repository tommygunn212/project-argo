"""Contract tests for context-aware classic clarification prompts."""

import random
from types import SimpleNamespace

import pytest

from core.intent_parser import IntentType
from core.pipeline import ArgoPipeline


@pytest.mark.parametrize(
    ("intent_type", "expected"),
    [
        (IntentType.APP_CONTROL, "Which app?"),
        (IntentType.APP_LAUNCH, "Which app should I open?"),
        (IntentType.MUSIC, "What would you like to hear?"),
        (IntentType.VOLUME_CONTROL, "Louder or quieter?"),
    ],
)
def test_clarification_prompt_targets_supported_intents(intent_type, expected):
    intent = SimpleNamespace(intent_type=intent_type)

    assert ArgoPipeline._get_clarification_prompt(None, intent) == expected


def test_clarification_prompt_uses_first_two_candidates_before_intent():
    intent = SimpleNamespace(intent_type=IntentType.MUSIC)

    assert ArgoPipeline._get_clarification_prompt(
        None, intent, ["Spotify", "Jellyfin", "YouTube"]
    ) == "Spotify or Jellyfin?"


def test_single_candidate_does_not_create_a_false_choice(monkeypatch):
    monkeypatch.setattr(random, "choice", lambda options: options[-1])

    assert ArgoPipeline._get_clarification_prompt(
        None, None, ["Spotify"]
    ) == "Not sure what to do with that one. What's the ask?"


def test_generic_clarification_uses_the_existing_quip_pool(monkeypatch):
    selected = {}

    def choose(options):
        selected["options"] = options
        return options[2]

    monkeypatch.setattr(random, "choice", choose)

    assert ArgoPipeline._get_clarification_prompt(None) == (
        "I caught words but not intent. What do you need?"
    )
    assert len(selected["options"]) == 6
    assert "Come again?" in selected["options"]
