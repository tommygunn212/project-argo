"""Deterministic policy for validating structured knowledge answers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Mapping


STRICT_INSTRUCTION_MODEL = "gpt-4.1"
SCHEMA_INSTRUCTION = (
    "You must answer using the following structure:\n\n"
    "Principle:\n<Name the underlying scientific, economic, or system principle>\n\n"
    "Explanation:\n<Explain the phenomenon using that principle in plain language>\n\n"
    "Do not omit the Principle section."
)
KNOWLEDGE_DOMAINS = {
    "knowledge_physics": (
        "heat", "cooling", "thermodynamics", "energy", "conduction",
        "convection", "radiation", "molecule", "evaporation", "law", "process",
    ),
    "knowledge_finance": (
        "store of value", "medium of exchange", "inflation", "currency", "money",
        "bitcoin", "asset", "liability", "investment", "finance", "bond", "stock", "blockchain",
    ),
    "knowledge_time_system": (
        "clock", "time source", "system", "status", "uptime", "cpu", "memory",
        "disk", "metric", "monitor",
    ),
}
FALLBACKS = {
    "knowledge_physics": (
        "Principle:\nHeat transfer and thermodynamics\n\n"
        "Explanation:\nObjects cool down because heat energy moves from warmer objects "
        "to cooler surroundings until temperatures equalize."
    ),
    "knowledge_finance": (
        "Principle:\nDefinition of money\n\n"
        "Explanation:\nMoney functions as a medium of exchange, store of value, and unit "
        "of account. Bitcoin partially satisfies these criteria."
    ),
    "knowledge_time_system": (
        "Principle:\nSystem clock and resource monitoring\n\n"
        "Explanation:\nThe current time comes from the system clock, while system status "
        "reflects CPU, memory, and other runtime metrics."
    ),
}


@dataclass(frozen=True)
class GuardResult:
    text: str
    outcome: str


def _principle_section(text: str) -> str:
    match = re.search(r"principle:\s*(.*?)(?:\n\s*explanation:|$)", text, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def answer_passes(text: str, intent_type: str) -> bool:
    keywords = KNOWLEDGE_DOMAINS.get(intent_type)
    if not keywords:
        return True
    section = _principle_section(text)
    return "principle:" in text.lower() and any(keyword in section for keyword in keywords)


def is_must_pass(text: str, intent_type: str, phrases: Mapping[str, str] | None) -> bool:
    normalized = text.strip().lower()
    return bool(phrases) and any(
        normalized == phrase.strip().lower() and mapped_intent == intent_type
        for phrase, mapped_intent in phrases.items()
    )


def enforce_knowledge_answer(
    *,
    initial_response: str,
    user_text: str,
    intent_type: str | None,
    confidence: float,
    must_pass_phrases: Mapping[str, str] | None,
    retry: Callable[[str, str | None], str],
    default_model: str,
) -> GuardResult:
    if intent_type not in KNOWLEDGE_DOMAINS or confidence < 0.95:
        return GuardResult(initial_response, "not_applicable")
    if answer_passes(initial_response, intent_type):
        return GuardResult(initial_response, "initial_pass")

    retry_model = None if default_model == STRICT_INSTRUCTION_MODEL else STRICT_INSTRUCTION_MODEL
    retry_response = retry(SCHEMA_INSTRUCTION, retry_model)
    if answer_passes(retry_response, intent_type):
        return GuardResult(retry_response, "retry_pass")
    if is_must_pass(user_text, intent_type, must_pass_phrases):
        fallback = FALLBACKS.get(intent_type, "[Error: No fallback template for this intent.]")
        return GuardResult(fallback + "\n[system_generated: true]", "must_pass_fallback")
    return GuardResult(
        retry_response + "\n[Warning: Principle section or domain keyword missing. Answer may be incomplete.]",
        "retry_weak",
    )
