"""Clarification prompt policy for the classic pipeline."""

import random
from collections.abc import Sequence
from typing import Protocol

from core.intent_parser import IntentType


class IntentLike(Protocol):
    intent_type: IntentType


CLARIFICATION_QUIPS = (
    "Come again?",
    "You gotta give me more than that.",
    "I caught words but not intent. What do you need?",
    "Say that again but with a destination.",
    "I'm listening, but I need a bit more.",
    "Not sure what to do with that one. What's the ask?",
)


def get_clarification_prompt(
    intent: IntentLike | None = None,
    candidates: Sequence[str] | None = None,
) -> str:
    """Return one targeted choice or an existing generic clarification quip."""

    if candidates and len(candidates) >= 2:
        return f"{candidates[0]} or {candidates[1]}?"

    if intent:
        if intent.intent_type == IntentType.APP_CONTROL:
            return "Which app?"
        if intent.intent_type == IntentType.APP_LAUNCH:
            return "Which app should I open?"
        if intent.intent_type == IntentType.MUSIC:
            return "What would you like to hear?"
        if intent.intent_type == IntentType.VOLUME_CONTROL:
            return "Louder or quieter?"

    return random.choice(CLARIFICATION_QUIPS)
