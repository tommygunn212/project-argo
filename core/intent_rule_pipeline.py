"""Ordered deterministic rule pipeline for intent classification."""

from __future__ import annotations

from typing import Protocol, Sequence

from core.intent_input import apply_phonetic_fixes, normalize_for_rules, strip_wake_prefix
from core.intent_models import Intent
from core.intent_rules.core_system import parse_control_intent, parse_full_system_status
from core.intent_rules.general import (
    parse_development_or_tech,
    parse_generic_utterance,
    parse_performance_intent,
)
from core.intent_rules.knowledge import parse_knowledge_intent, parse_must_pass_knowledge
from core.intent_rules.router import parse_domain_intent


class IntentRuleContext(Protocol):
    """Vocabulary and state needed by the ordered rule pipeline."""

    serious_mode: bool
    serious_mode_keywords: Sequence[str]
    sleep_phrases: Sequence[str]
    develop_phrases: Sequence[str]
    tech_keywords: Sequence[str]
    question_words: Sequence[str]
    greeting_keywords: Sequence[str]
    command_words: Sequence[str]

    def _parse_music_intent(
        self, text_original: str, text_lower: str, serious_mode: bool
    ) -> Intent | None: ...


def parse_intent_rules(parser: IntentRuleContext, text: str) -> Intent:
    """Classify text in the established, behavior-sensitive rule order."""
    if not text or not text.strip():
        raise ValueError("text is empty")

    text_original = text.strip()
    text_lower = normalize_for_rules(text_original)
    parser.serious_mode = any(
        keyword in text_lower for keyword in parser.serious_mode_keywords
    )
    serious_mode = parser.serious_mode

    must_pass = parse_must_pass_knowledge(text_original, serious_mode)
    if must_pass is not None:
        return must_pass

    text_lower = apply_phonetic_fixes(text_lower)
    parser.serious_mode = any(
        keyword in text_lower for keyword in parser.serious_mode_keywords
    )
    serious_mode = parser.serious_mode

    system_status = parse_full_system_status(
        text_original, text_lower, serious_mode
    )
    if system_status is not None:
        return system_status

    prepared = strip_wake_prefix(text_original, text_lower)
    text_original = prepared.original
    text_lower = prepared.normalized

    control_intent = parse_control_intent(
        text_original, text_lower, serious_mode, parser.sleep_phrases
    )
    if control_intent is not None:
        return control_intent

    domain_intent = parse_domain_intent(text_original, text_lower, serious_mode)
    if domain_intent is not None:
        return domain_intent

    contextual_intent = parse_development_or_tech(
        text_original,
        text_lower,
        serious_mode,
        parser.develop_phrases,
        parser.tech_keywords,
    )
    if contextual_intent is not None:
        return contextual_intent

    music_intent = parser._parse_music_intent(
        text_original, text_lower, serious_mode
    )
    if music_intent is not None:
        return music_intent

    performance_intent = parse_performance_intent(
        text_original, prepared.tokens, serious_mode
    )
    if performance_intent is not None:
        return performance_intent

    knowledge_intent = parse_knowledge_intent(
        text_original, text_lower, serious_mode
    )
    if knowledge_intent is not None:
        return knowledge_intent

    return parse_generic_utterance(
        text_original,
        prepared.first_word,
        serious_mode,
        parser.question_words,
        parser.greeting_keywords,
        parser.command_words,
    )
