"""Terminal conversation gates for the classic pipeline."""

from __future__ import annotations

import re
from typing import Any


def _finish(
    pipeline: Any,
    response: str,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
    *,
    record_ledger: bool = False,
) -> None:
    pipeline.broadcast("log", f"Argo: {response}")
    if record_ledger:
        pipeline._append_convo_ledger("argo", response)
    if not pipeline.stop_signal.is_set() and not replay_mode:
        tts_text = pipeline._sanitize_tts_text(response)
        if (overrides or {}).get("suppress_tts", False):
            pipeline.logger.info("[TTS] Suppressed for next interaction override")
        elif tts_text:
            pipeline.speak(tts_text, interaction_id=interaction_id)
    pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
    pipeline.logger.info("--- Interaction Complete ---")
    pipeline._record_timeline(
        "INTERACTION_END", stage="pipeline", interaction_id=interaction_id
    )


def _confirm_pending_name(
    pipeline: Any,
    user_text: str,
    interaction_id: str,
) -> str:
    if not pipeline._is_affirmative_response(user_text):
        pipeline.logger.info(
            "[MEMORY] write_aborted user_response_negative_or_topic_change"
        )
        response = "Okay."
    elif not pipeline._pending_memory:
        response = "No pending memory to write."
    else:
        try:
            pending_key = pipeline._pending_memory.get("key")
            pending_value = pipeline._pending_memory.get("value")
            if pending_key and pending_value:
                pipeline._memory_store.add_memory(
                    "FACT",
                    pending_key,
                    pending_value,
                    source="explicit_user_request",
                )
                pipeline._store_mem0_fact(
                    "fact",
                    pending_key,
                    "is",
                    pending_value,
                    "explicit_user_request",
                    interaction_id,
                )
            else:
                pipeline.logger.warning(
                    "[MEMORY] Pending memory missing key or value"
                )
            pipeline.logger.info(
                f"[MEMORY] write_confirmed key=name value={pipeline._pending_memory.get('value')}"
            )
            response = "Got it. I'll remember that."
        except Exception as exc:
            pipeline.logger.warning(f"[MEMORY] Name write failed: {exc}")
            response = "Memory store unavailable."

    pipeline._pending_memory = None
    pipeline._session_flags["confirm_name"] = False
    return response


def dispatch_conversation_gate(
    pipeline: Any,
    user_text: str,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> bool:
    """Handle terminal pre-routing conversation cases in their original order."""
    if not user_text:
        _finish(
            pipeline,
            "I didn't catch any words. Try again.",
            interaction_id,
            replay_mode,
            overrides,
        )
        return True

    if pipeline._session_flags.get("confirm_name", False):
        response = _confirm_pending_name(pipeline, user_text, interaction_id)
        _finish(
            pipeline,
            response,
            interaction_id,
            replay_mode,
            overrides,
            record_ledger=True,
        )
        return True

    if user_text.lower().strip() == "clear conversation":
        pipeline._conversation_ledger.clear()
        pipeline.logger.info("[CONVO] convo_ledger_size=0")
        _finish(
            pipeline,
            "Conversation cleared.",
            interaction_id,
            replay_mode,
            overrides,
        )
        return True

    if not pipeline.strict_lab_mode and pipeline._is_identity_query(user_text):
        pipeline._respond_with_identity_lookup(
            interaction_id=interaction_id,
            replay_mode=replay_mode,
            overrides=overrides,
        )
        return True

    filler_match = re.fullmatch(
        r"(okay\.?\s*)+|\.+", user_text, flags=re.IGNORECASE
    )
    if not pipeline.strict_lab_mode and filler_match:
        _finish(
            pipeline,
            "Okay.",
            interaction_id,
            replay_mode,
            overrides,
            record_ledger=True,
        )
        return True
    return False
