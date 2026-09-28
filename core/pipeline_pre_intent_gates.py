"""Pre-intent terminal gates for the classic pipeline."""

from __future__ import annotations

from typing import Any


def _finish_contextual_reply(
    pipeline: Any,
    response: str,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> None:
    pipeline.broadcast("log", f"Argo: {response}")
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


def dispatch_pre_intent_gate(
    pipeline: Any,
    user_text: str,
    request_kind: str,
    topic: str | None,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> bool:
    """Handle terminal gates that run before parsed-intent dispatch."""
    if pipeline._is_non_propositional_utterance(user_text, request_kind):
        pipeline.logger.info(
            "[LLM] Non-propositional utterance detected; prompting for clarification"
        )
        pipeline._record_timeline(
            "NON_PROPOSITIONAL_GUARD",
            stage="pipeline",
            interaction_id=interaction_id,
        )
        pipeline._respond_with_clarification(
            interaction_id, replay_mode, overrides
        )
        return True

    if request_kind == "QUESTION" and not pipeline.strict_lab_mode:
        assert topic is None, "Personal mode questions must never be blocked"

    stop_terms = {"stop", "pause", "cancel", "shut up", "shutup", "shut-up"}
    if any(term in user_text.lower() for term in stop_terms):
        pipeline._conversation_buffer.clear(reason="STOP detected")
        from core.music_player import get_music_player

        music_player = get_music_player()
        if music_player.is_playing():
            pipeline.logger.info("[ARGO] Active music detected")
            music_player.stop()
            pipeline.transition_state(
                "LISTENING", interaction_id=interaction_id, source="audio"
            )
            return True

    if pipeline._handle_memory_command(
        user_text, interaction_id, replay_mode, overrides
    ):
        pipeline.transition_state(
            "LISTENING", interaction_id=interaction_id, source="audio"
        )
        pipeline.logger.info("--- Interaction Complete ---")
        pipeline._record_timeline(
            "INTERACTION_END", stage="pipeline", interaction_id=interaction_id
        )
        return True

    contextual_reply = pipeline._handle_contextual_followup(user_text)
    if contextual_reply:
        _finish_contextual_reply(
            pipeline,
            contextual_reply,
            interaction_id,
            replay_mode,
            overrides,
        )
        return True
    return False
