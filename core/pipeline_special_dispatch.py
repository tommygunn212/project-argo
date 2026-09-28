"""Special local intent routing for the classic conversation pipeline."""

from __future__ import annotations

from typing import Any

from core.intent_parser import IntentType


def _respond_with_count(
    pipeline: Any,
    user_text: str,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> bool:
    response = pipeline._build_count_response(user_text)
    pipeline.broadcast("log", f"Argo: {response}")
    if not pipeline.stop_signal.is_set() and not replay_mode:
        tts_text = pipeline._sanitize_tts_text(response, enforce_confidence=False)
        if (overrides or {}).get("suppress_tts", False):
            pipeline.logger.info("[TTS] Suppressed for next interaction override")
        elif tts_text:
            pipeline.speak(tts_text, interaction_id=interaction_id)
    pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
    pipeline.logger.info("--- Interaction Complete ---")
    pipeline._record_timeline(
        "INTERACTION_END", stage="pipeline", interaction_id=interaction_id
    )
    return True


def dispatch_special_intent(
    pipeline: Any,
    intent: Any,
    user_text: str,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> bool:
    """Handle local special cases while allowing identity to reach the LLM."""
    if intent is None:
        return False

    intent_type = intent.intent_type
    if intent_type == IntentType.SILENCE_OVERRIDE:
        return bool(
            pipeline._respond_with_silence_override(
                interaction_id, replay_mode, overrides
            )
        )
    if intent_type == IntentType.ARGO_IDENTITY:
        pipeline.logger.info(
            "[INTENT] ARGO_IDENTITY detected; routing to LLM with persona"
        )
        return False
    if intent_type == IntentType.ARGO_GOVERNANCE:
        return bool(
            pipeline._respond_with_argo_governance(
                intent, interaction_id, replay_mode, overrides
            )
        )
    if intent_type == IntentType.COUNT:
        return _respond_with_count(
            pipeline, user_text, interaction_id, replay_mode, overrides
        )
    if intent_type in {IntentType.SYSTEM_HEALTH, IntentType.SYSTEM_STATUS}:
        return bool(
            pipeline._respond_with_system_health(
                user_text, intent, interaction_id, replay_mode, overrides
            )
        )
    if intent_type == IntentType.SELF_DIAGNOSTICS:
        return bool(
            pipeline._respond_with_self_diagnostics(
                interaction_id, replay_mode, overrides
            )
        )
    return False
