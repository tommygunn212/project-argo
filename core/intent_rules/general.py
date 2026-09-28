"""Generic intent rules that run around the domain-specific parsers."""

from __future__ import annotations

from collections.abc import Collection

from core.intent_models import Intent, IntentType


PERFORMANCE_WORDS = frozenset({"count", "sing", "recite", "spell", "list", "name"})


def parse_development_or_tech(
    raw_text: str,
    normalized: str,
    serious_mode: bool,
    develop_phrases: Collection[str],
    tech_keywords: Collection[str],
) -> Intent | None:
    if any(phrase in normalized for phrase in develop_phrases):
        return Intent(IntentType.DEVELOP, 0.98, raw_text, serious_mode=serious_mode)
    if any(keyword in normalized for keyword in tech_keywords):
        return Intent(IntentType.QUESTION, 0.9, raw_text, serious_mode=serious_mode)
    return None


def parse_performance_intent(
    raw_text: str,
    tokens: Collection[str],
    serious_mode: bool,
) -> Intent | None:
    if "count" in tokens:
        return Intent(IntentType.COUNT, 0.9, raw_text, serious_mode=serious_mode)
    if any(word in tokens for word in PERFORMANCE_WORDS):
        return Intent(IntentType.COMMAND, 0.9, raw_text, serious_mode=serious_mode)
    return None


def parse_generic_utterance(
    raw_text: str,
    first_word: str,
    serious_mode: bool,
    question_words: Collection[str],
    greeting_keywords: Collection[str],
    command_words: Collection[str],
) -> Intent:
    if "?" in raw_text:
        return Intent(IntentType.QUESTION, 1.0, raw_text, serious_mode=serious_mode)
    if first_word in question_words:
        return Intent(IntentType.QUESTION, 0.85, raw_text, serious_mode=serious_mode)
    if first_word in greeting_keywords:
        return Intent(IntentType.GREETING, 0.95, raw_text, serious_mode=serious_mode)
    if first_word in command_words:
        return Intent(IntentType.COMMAND, 0.75, raw_text, serious_mode=serious_mode)
    return Intent(IntentType.UNKNOWN, 0.1, raw_text, serious_mode=serious_mode)
