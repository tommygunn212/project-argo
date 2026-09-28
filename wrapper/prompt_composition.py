"""Behavior selection and prompt composition for the legacy wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from system.runtime.drift_monitor import get_drift_monitor
from wrapper.behavior_policy import (
    build_behavior_instruction,
    classify_query_type,
    get_familiarity_level,
    infer_canonical_knowledge,
    is_casual_question,
    select_behavior_profile,
    select_primary_frame,
)
from wrapper.cli_policy import (
    get_cli_formatting_suppression,
    get_persona_text,
    get_verbosity_text,
)
from wrapper.conversation_history import detect_context, get_confidence_instruction


TRUSTED_CASUAL_CONSTRAINT = (
    "RESPOND ACCORDING TO THIS CONSTRAINT, NO EXCEPTIONS:\n\n"
    "Your first sentence must be a direct claim about causation.\n"
    "Your first sentence MUST start with exactly one of these:\n"
    '1. "People do this because"\n'
    '2. "What\'s really happening is"\n'
    '3. "This happens because"\n\n'
    "Your first sentence MUST NOT start with any of these:\n"
    '- "The phenomenon"\n'
    '- "This behavior"\n'
    '- "In humans"\n'
    '- "This can be attributed"\n'
    '- "Research suggests"\n\n'
    "After you answer the first sentence, you can explain as needed.\n"
    "But DO NOT open with academic framing or neutral exposition.\n"
    "Stay in human voice from the first word."
)


@dataclass(frozen=True)
class PromptComposition:
    full_prompt: bytes
    classified_verbosity: str
    execution_context: str
    query_type: str
    has_canonical_knowledge: bool
    behavior_profile: dict[str, Any]
    is_casual_question: bool
    primary_frame: str
    drift_monitor: Any
    uncertainty_enforcement: dict[str, Any] | None


def compose_prompt(
    *,
    user_input: str,
    active_mode: str | None,
    persona: str,
    classified_verbosity: str,
    context_strength: str,
    replay_block: str,
    voice_mode: bool,
    mode_enforcement: str,
) -> PromptComposition:
    """Select behavior policy and build the encoded Ollama prompt."""
    execution_context = detect_context()
    if execution_context == "cli":
        context_strength = "weak"

    query_type = classify_query_type(user_input)
    has_canonical_knowledge = infer_canonical_knowledge(user_input)
    behavior_profile = select_behavior_profile(
        query_type, context_strength, has_canonical_knowledge
    )
    casual_question = is_casual_question(user_input)
    primary_frame = select_primary_frame(
        query_type, context_strength, casual_question
    )
    familiarity_level = get_familiarity_level()
    behavior_instruction = build_behavior_instruction(
        behavior_profile,
        execution_context,
        has_canonical_knowledge,
        primary_frame,
        familiarity_level,
        user_input,
        casual_question,
        voice_mode,
    )

    if behavior_profile["verbosity_override"]:
        classified_verbosity = behavior_profile["verbosity_override"]

    drift_monitor = get_drift_monitor()
    uncertainty_enforcement = drift_monitor.check_preconditions_uncertainty(
        query_type=query_type,
        has_canonical_knowledge=has_canonical_knowledge,
        query_demands_certainty=query_type in {"factual", "instructional"},
    )
    drift_corrections = drift_monitor.apply_corrections()
    if drift_corrections.get("force_verbosity"):
        classified_verbosity = drift_corrections["force_verbosity"]
    if drift_corrections.get("force_explanation_depth"):
        behavior_profile["explanation_depth"] = drift_corrections[
            "force_explanation_depth"
        ]

    persona_text = get_persona_text(persona)
    verbosity_text = get_verbosity_text(classified_verbosity)
    cli_formatting_text = get_cli_formatting_suppression(execution_context)
    confidence_text = get_confidence_instruction(context_strength)
    uncertainty_text = ""
    if uncertainty_enforcement:
        uncertainty_text = (
            "You lack canonical knowledge on this topic. "
            "Provide only what you can verify. "
            f"Required phrasing: {uncertainty_enforcement['require_phrases'][0]}. "
            f"Prohibited: {', '.join(uncertainty_enforcement['prohibit_phrases'])}. "
            "Declare gaps explicitly."
        )

    prompt_parts = []
    if familiarity_level == "trusted" and casual_question:
        prompt_parts.append(TRUSTED_CASUAL_CONSTRAINT)
    if active_mode:
        prompt_parts.append(mode_enforcement)
    if persona_text:
        prompt_parts.append(persona_text)
    prompt_parts.append(behavior_instruction)
    if uncertainty_text:
        prompt_parts.append(uncertainty_text)
    prompt_parts.append(verbosity_text)
    if cli_formatting_text:
        prompt_parts.append(cli_formatting_text)
    prompt_parts.append(confidence_text)
    if replay_block:
        prompt_parts.append(replay_block.rstrip())
    prompt_parts.append(user_input)

    return PromptComposition(
        full_prompt="\n\n".join(prompt_parts).encode("utf-8"),
        classified_verbosity=classified_verbosity,
        execution_context=execution_context,
        query_type=query_type,
        has_canonical_knowledge=has_canonical_knowledge,
        behavior_profile=behavior_profile,
        is_casual_question=casual_question,
        primary_frame=primary_frame,
        drift_monitor=drift_monitor,
        uncertainty_enforcement=uncertainty_enforcement,
    )
