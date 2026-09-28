"""Clarification prompt policy for the classic pipeline."""

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Callable, Protocol

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


@dataclass(frozen=True)
class ClarificationDeliveryDependencies:
    clear_conversation: Callable[..., None]
    logger: Any
    broadcast: Callable[[str, str], None]
    append_conversation: Callable[[str, str], None]
    sanitize_tts_text: Callable[..., str]
    speak: Callable[..., None]
    transition_state: Callable[..., None]
    record_timeline: Callable[..., None]
    apply_persona: Callable[[str, Any, str], str]


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


def deliver_clarification(
    dependencies: ClarificationDeliveryDependencies,
    *,
    response: str,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict | None,
    persona_name: str,
    response_type: Any,
    stop_requested: bool,
) -> bool:
    """Reset context, emit one clarification, and finish the interaction."""

    dependencies.clear_conversation(reason="clarification/error")
    response = dependencies.apply_persona(response, response_type, persona_name)
    dependencies.logger.info(f"[CLARIFY] {response}")
    dependencies.broadcast("log", f"Argo: {response}")
    dependencies.append_conversation("argo", response)

    if not stop_requested and not replay_mode:
        tts_text = dependencies.sanitize_tts_text(
            response, enforce_confidence=False
        )
        tts_override = (overrides or {}).get("suppress_tts", False)
        if not tts_override and tts_text:
            dependencies.speak(tts_text, interaction_id=interaction_id)

    dependencies.transition_state(
        "LISTENING", interaction_id=interaction_id, source="audio"
    )
    dependencies.logger.info("--- Interaction Complete ---")
    dependencies.record_timeline(
        "INTERACTION_END", stage="pipeline", interaction_id=interaction_id
    )
    return True
