"""Replay selection, filtering, budgeting, and prompt formatting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wrapper.conversation_history import (
    apply_replay_budget,
    classify_context_strength,
    classify_entry_type,
    filter_replay_entries,
    get_last_n_entries,
    get_session_entries,
)


@dataclass(frozen=True)
class ReplayContext:
    block: str = ""
    policy: dict[str, Any] | None = None
    context_strength: str = "weak"


def build_replay_context(
    *,
    session_id: str,
    replay_n: int | None,
    replay_session: bool,
    replay_reason: str,
    voice_mode: bool,
) -> ReplayContext:
    """Build bounded replay context, or an empty context for stateless turns."""
    if not voice_mode and replay_session:
        entries = get_session_entries(session_id)
    elif not voice_mode and replay_n:
        entries = get_last_n_entries(replay_n)
    else:
        entries = []

    if not entries:
        return ReplayContext()

    entry_types = [
        classify_entry_type(
            entry.get("user_prompt", ""), entry.get("model_response", "")
        )
        for entry in entries
    ]
    entries, filter_stats = filter_replay_entries(
        entries, replay_reason, entry_types
    )
    entry_types = [
        classify_entry_type(
            entry.get("user_prompt", ""), entry.get("model_response", "")
        )
        for entry in entries
    ]
    entries, replay_stats = apply_replay_budget(entries, max_chars=5500)
    policy = {**filter_stats, **replay_stats, "reason": replay_reason}
    context_strength = classify_context_strength(policy, entry_types)
    policy["context_strength"] = context_strength

    replay_lines = []
    for entry in entries:
        replay_lines.append(f"User: {entry['user_prompt']}")
        replay_lines.append(f"Assistant: {entry['model_response']}")
    return ReplayContext(
        block="\n".join(replay_lines) + "\n\n",
        policy=policy,
        context_strength=context_strength,
    )
