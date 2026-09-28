"""Response validation, drift accounting, durable logging, and memory storage."""

from __future__ import annotations

from datetime import datetime
import sys
from typing import Any

from wrapper.behavior_policy import (
    detect_plausible_hallucination,
    update_familiarity,
    validate_human_first_sentence,
    validate_personality_discipline,
    validate_scope,
)
from wrapper.cli_policy import validate_cli_format
from wrapper.conversation_history import _append_daily_log
from wrapper.memory import store_interaction
from wrapper.prompt_composition import PromptComposition


def audit_and_record_response(
    *,
    user_input: str,
    output: str,
    prompt: PromptComposition,
    session_id: str,
    active_mode: str | None,
    replay_n: int | None,
    replay_session: bool,
    replay_policy: dict[str, Any] | None,
    persona: str,
) -> None:
    """Apply post-generation policy checks and persist one interaction."""
    cli_valid, cli_error = validate_cli_format(output, prompt.execution_context)
    if not cli_valid:
        print(f"⚠ CLI Format Violation: {cli_error}", file=sys.stderr)

    scope_valid, _scope_drift = validate_scope(output)
    if not scope_valid:
        prompt.drift_monitor.flag_signal(
            "scope_expansion", {"force_verbosity": "short"}, duration=2
        )

    personality_valid, _violation, soft_failure = validate_personality_discipline(
        output,
        prompt.query_type,
        prompt.has_canonical_knowledge,
        prompt.execution_context,
        prompt.is_casual_question,
    )
    if not personality_valid:
        update_familiarity(False, "personality_discipline")
    elif not soft_failure:
        update_familiarity(True)

    human_first_valid, _human_violation = validate_human_first_sentence(
        output, prompt.is_casual_question, prompt.primary_frame
    )
    if not human_first_valid:
        update_familiarity(False, "frame_blending")

    # This is intentionally a soft check: the result is diagnostic and does
    # not demote familiarity without a separate hard policy violation.
    detect_plausible_hallucination(
        output, prompt.has_canonical_knowledge, prompt.primary_frame
    )

    prompt.drift_monitor.log_interaction(
        user_prompt=user_input,
        model_response=output,
        query_type=prompt.query_type,
        has_canonical_knowledge=prompt.has_canonical_knowledge,
        behavior_profile=prompt.behavior_profile,
        verbosity=prompt.classified_verbosity,
    )
    violations = prompt.drift_monitor.detect_violations()
    drift_signals = prompt.drift_monitor.detect_drift()
    for signal in drift_signals:
        prompt.drift_monitor.flag_signal(
            signal["signal"],
            signal["corrective_action"],
            signal["duration_turns"],
        )

    behavior_log = {
        "query_type": prompt.query_type,
        "verbosity_override": prompt.behavior_profile["verbosity_override"],
        "explanation_depth": prompt.behavior_profile["explanation_depth"],
        "correction_style": prompt.behavior_profile["correction_style"],
    }
    honesty_log = {
        "uncertainty_enforced": prompt.uncertainty_enforcement is not None,
        "violations_detected": len(violations),
        "drift_signals_detected": len(drift_signals),
    }
    if violations:
        honesty_log["violations"] = [item["type"] for item in violations]
    if drift_signals:
        honesty_log["drift_signals"] = [item["signal"] for item in drift_signals]

    _append_daily_log(
        timestamp_iso=datetime.now().isoformat(timespec="seconds"),
        session_id=session_id,
        user_prompt=user_input,
        model_response=output,
        active_mode=active_mode,
        replay_n=replay_n,
        replay_session=replay_session,
        persona=persona,
        verbosity=prompt.classified_verbosity,
        replay_policy=replay_policy,
        behavior_profile=behavior_log,
        honesty_enforcement=honesty_log,
    )

    original_input = user_input
    if original_input.startswith("From your history:"):
        parts = original_input.split("\n\n", 1)
        if len(parts) > 1:
            original_input = parts[1]
    store_interaction(original_input, output)
