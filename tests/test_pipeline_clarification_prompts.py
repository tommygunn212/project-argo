"""Contract tests for context-aware classic clarification prompts."""

import random
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.intent_parser import IntentType
from core.pipeline import ArgoPipeline
from personas import ResponseType


def _delivery_pipeline():
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline._conversation_buffer = Mock()
    pipeline._get_clarification_prompt = Mock(return_value="generated prompt")
    pipeline._resolve_personality_mode = Mock(return_value="plain")
    pipeline.logger = Mock()
    pipeline.broadcast = Mock()
    pipeline._append_convo_ledger = Mock()
    pipeline.stop_signal = threading.Event()
    pipeline._sanitize_tts_text = Mock(return_value="spoken prompt")
    pipeline.speak = Mock()
    pipeline.transition_state = Mock()
    pipeline._record_timeline = Mock()
    return pipeline


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


def test_clarification_delivery_resets_context_and_finishes(monkeypatch):
    pipeline = _delivery_pipeline()
    apply_persona = Mock(return_value="persona prompt")
    monkeypatch.setattr("core.pipeline.apply_persona", apply_persona)

    result = pipeline._respond_with_clarification(
        "turn-1", False, None, prompt="explicit prompt"
    )

    assert result is True
    pipeline._conversation_buffer.clear.assert_called_once_with(
        reason="clarification/error"
    )
    pipeline._get_clarification_prompt.assert_not_called()
    apply_persona.assert_called_once_with(
        "explicit prompt", ResponseType.CLARIFICATION, "plain"
    )
    pipeline.broadcast.assert_called_once_with("log", "Argo: persona prompt")
    pipeline._append_convo_ledger.assert_called_once_with("argo", "persona prompt")
    pipeline.speak.assert_called_once_with("spoken prompt", interaction_id="turn-1")
    pipeline.transition_state.assert_called_once_with(
        "LISTENING", interaction_id="turn-1", source="audio"
    )
    pipeline._record_timeline.assert_called_once_with(
        "INTERACTION_END", stage="pipeline", interaction_id="turn-1"
    )


def test_clarification_delivery_generates_prompt_and_honors_tts_suppression(
    monkeypatch,
):
    pipeline = _delivery_pipeline()
    monkeypatch.setattr("core.pipeline.apply_persona", lambda message, *_: message)
    intent = SimpleNamespace(intent_type=IntentType.MUSIC)

    pipeline._respond_with_clarification(
        "turn-2",
        False,
        {"suppress_tts": True},
        intent=intent,
        candidates=["one", "two"],
    )

    pipeline._get_clarification_prompt.assert_called_once_with(
        intent, ["one", "two"]
    )
    pipeline._sanitize_tts_text.assert_called_once_with(
        "generated prompt", enforce_confidence=False
    )
    pipeline.speak.assert_not_called()


def test_replayed_clarification_never_enters_tts_path(monkeypatch):
    pipeline = _delivery_pipeline()
    monkeypatch.setattr("core.pipeline.apply_persona", lambda message, *_: message)

    pipeline._respond_with_clarification("turn-3", True, None)

    pipeline._sanitize_tts_text.assert_not_called()
    pipeline.speak.assert_not_called()
