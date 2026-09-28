"""Preference, recall, and history composition for wrapper interactions."""

from __future__ import annotations

from dataclasses import dataclass

from wrapper.conversation_history import detect_recall_query, format_recall_response
from wrapper.memory import find_relevant_memory, load_memory
from wrapper.prefs import build_pref_block, load_prefs, save_prefs, update_prefs


@dataclass(frozen=True)
class ConversationPreparation:
    composed_input: str
    recall_output: str | None = None

    @property
    def is_recall(self) -> bool:
        return self.recall_output is not None


def update_preferences(user_input: str) -> dict:
    """Load, update, and persist user presentation preferences."""
    prefs = update_prefs(user_input, load_prefs())
    save_prefs(prefs)
    return prefs


def prepare_conversation(
    user_input: str,
    *,
    prefs: dict,
    voice_mode: bool,
) -> ConversationPreparation:
    """Resolve recall or build the exact model input for one interaction."""
    is_recall, count_requested = detect_recall_query(user_input)
    if is_recall:
        return ConversationPreparation(
            composed_input=user_input,
            recall_output=format_recall_response(
                load_memory(), count=count_requested, prefs=prefs
            ),
        )

    if voice_mode:
        return ConversationPreparation(composed_input=user_input)

    relevant_memory = find_relevant_memory(user_input, top_n=2)
    memory_context = ""
    if relevant_memory:
        memory_lines = []
        for item in relevant_memory:
            memory_lines.append(f"Past: {item['user_input']}")
            memory_lines.append(f"Response: {item['model_response']}")
        memory_context = "From your history:\n" + "\n".join(memory_lines) + "\n\n"
    return ConversationPreparation(
        composed_input=build_pref_block(prefs) + memory_context + user_input
    )
