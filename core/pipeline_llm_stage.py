"""Conversational LLM stage for the classic pipeline."""

from __future__ import annotations

from typing import Any

from personas import ResponseType, apply_persona


def run_llm_stage(
    pipeline: Any,
    intent: Any,
    user_text: str,
    request_kind: str,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
    audio_data: Any,
) -> None:
    """Retrieve context, stream the answer, and persist a completed turn."""
    rag_context = ""
    memory_context = ""
    llm_context_scope = "isolated"
    if request_kind == "QUESTION":
        # Brain: update working memory BEFORE LLM call
        _intent_str = getattr(getattr(intent, 'intent_type', None), 'value', '') if intent else ''
        try:
            pipeline._brain.before_llm(user_text, _intent_str)
        except Exception as e:
            pipeline.logger.warning(f"[BRAIN] before_llm failed: {e}")

        context, missing = pipeline._context_fetcher.fetch({
            "rag": lambda: pipeline._get_rag_context(user_text, interaction_id),
            "memory": lambda: pipeline._get_memory_context(interaction_id, user_text=user_text),
        }, timeout=5.0, stop=pipeline.stop_signal)
        rag_context = context.get("rag", "")
        memory_context = context.get("memory", "")
        if missing:
            pipeline.logger.warning("[CONTEXT] Skipped unavailable retrieval: %s", ", ".join(missing))
            pipeline._record_timeline("CONTEXT_INCOMPLETE " + ",".join(missing),
                                  stage="context", interaction_id=interaction_id)

        # Brain provides its own last-exchange context, so always mark as buffered
        llm_context_scope = "buffered"
        pipeline.logger.info(f"[LLM] Brain memory context active")

    pipeline.transition_state("THINKING", interaction_id=interaction_id, source="llm")
    pipeline.logger.info(f"[LLM] context_scope={llm_context_scope}")

    # ── Sentence-level streaming: LLM → TTS pipelined ──
    # TTS starts speaking the first sentence while LLM generates the rest.
    ai_text = pipeline._generate_and_speak_streamed(
        user_text,
        interaction_id=interaction_id,
        rag_context=rag_context,
        memory_context=memory_context,
        use_convo_buffer=(llm_context_scope == "buffered"),
        replay_mode=replay_mode,
        overrides=overrides,
    )
    ai_text = ai_text or ""
    ai_text = pipeline._strip_disallowed_phrases(ai_text)

    # Apply persona formatting for logging (TTS already played per-sentence)
    persona_name = pipeline._resolve_personality_mode()
    ai_text = apply_persona(ai_text, ResponseType.ANSWER, persona_name)

    if not ai_text.strip():
        pipeline.logger.warning("[LLM] Empty response")
        recovery = getattr(pipeline, "recovery_manager", None)
        if recovery is not None and not replay_mode:
            # Retry only conversational generation, never re-dispatch an
            # intent which may send mail, change devices, or write files.
            recovery.retry_callback = lambda: pipeline._generate_and_speak_streamed(
                user_text, interaction_id=interaction_id, rag_context=rag_context,
                memory_context=memory_context, use_convo_buffer=False,
                replay_mode=False, overrides=overrides)
        pipeline.broadcast("log", "Argo: [No response]")
        pipeline._recover_failed_turn(interaction_id)
        return
    # NOTE: broadcast already sent inside _generate_and_speak_streamed (before TTS wait)
    if getattr(pipeline, "recovery_manager", None):
        pipeline.recovery_manager.retry_callback = None
    pipeline._conversation_buffer.add("Assistant", ai_text)
    pipeline._append_convo_ledger("argo", ai_text)

    # Brain: store short-term exchange AFTER LLM response
    _intent_str = getattr(getattr(intent, 'intent_type', None), 'value', '') if intent else ''
    try:
        pipeline._brain.after_llm(user_text, ai_text, _intent_str)
    except Exception as e:
        pipeline.logger.warning(f"[BRAIN] after_llm failed: {e}")
    pipeline._store_durable_turn(user_text, ai_text, _intent_str, interaction_id)

    # TTS already played via streaming pipeline above — no separate speak() call needed

    pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
    pipeline.logger.info("--- Interaction Complete ---")
    pipeline._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)

    if not replay_mode and audio_data is not None:
        pipeline._save_replay(
            interaction_id=interaction_id,
            audio_data=audio_data,
            user_text=user_text,
            ai_text=ai_text,
        )

    return
