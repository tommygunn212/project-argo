"""Acquired classic-turn processing behind explicit callback dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class InteractionDependencies:
    logger: Any
    acquire_audio: Callable[..., None]
    release_audio: Callable[..., None]
    transcribe: Callable[..., str]
    read_stt_metrics: Callable[[], dict[str, Any] | None]
    set_stt_confidence: Callable[[float], None]
    normalize_text: Callable[[str], str]
    normalize_music_text: Callable[[str], str]
    is_prompt_echo: Callable[[str, float], bool]
    record_timeline: Callable[..., None]
    transition_state: Callable[..., None]
    broadcast: Callable[[str, Any], None]
    add_conversation_turn: Callable[[str, str], None]
    broadcast_turn_info: Callable[[], None]
    append_conversation_ledger: Callable[[str, str], None]
    handle_user_text: Callable[..., Any]


def process_interaction_audio(
    dependencies: InteractionDependencies,
    audio_data: Any,
    *,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> None:
    """Process one turn after the pipeline has acquired its turn lock."""
    dependencies.logger.info(
        f"--- Starting Interaction ({len(audio_data)} samples) ---"
    )
    dependencies.record_timeline(
        "INTERACTION_START", stage="pipeline", interaction_id=interaction_id
    )
    dependencies.transition_state(
        "TRANSCRIBING", interaction_id=interaction_id, source="audio"
    )
    print(f"DEBUG: Processing audio... {audio_data.shape}")

    try:
        dependencies.acquire_audio("STT", interaction_id=interaction_id)
    except Exception as exc:
        dependencies.logger.error(f"[STT] Audio ownership error: {exc}")
        dependencies.record_timeline(
            "STT_AUDIO_CONTESTED", stage="audio", interaction_id=interaction_id
        )
        return

    try:
        user_text = dependencies.transcribe(
            audio_data, interaction_id=interaction_id
        )
    finally:
        dependencies.release_audio("STT", interaction_id=interaction_id)

    confidence_hint = 1.0
    stt_metrics = dependencies.read_stt_metrics()
    if stt_metrics and "confidence" in stt_metrics:
        confidence_hint = stt_metrics["confidence"]
    dependencies.set_stt_confidence(confidence_hint)

    if not user_text:
        dependencies.logger.warning("No speech recognized.")
        dependencies.broadcast("log", "User: [No speech recognized]")
        dependencies.transition_state(
            "LISTENING", interaction_id=interaction_id, source="audio"
        )
        dependencies.logger.info("--- Interaction Complete (no speech) ---")
        dependencies.record_timeline(
            "INTERACTION_END", stage="pipeline", interaction_id=interaction_id
        )
        return

    user_text = dependencies.normalize_text(user_text)
    user_text = dependencies.normalize_music_text(user_text)
    if dependencies.is_prompt_echo(user_text, confidence_hint):
        dependencies.logger.warning(
            "[STT] Ignoring low-confidence prompt echo: %r (confidence=%.2f)",
            user_text,
            confidence_hint,
        )
        dependencies.record_timeline(
            "STT_PROMPT_ECHO_IGNORED",
            stage="stt",
            interaction_id=interaction_id,
        )
        dependencies.transition_state(
            "LISTENING", interaction_id=interaction_id, source="audio"
        )
        dependencies.record_timeline(
            "INTERACTION_END", stage="pipeline", interaction_id=interaction_id
        )
        return

    dependencies.broadcast("log", f"User: {user_text}")
    dependencies.add_conversation_turn("User", user_text)
    dependencies.broadcast_turn_info()
    dependencies.append_conversation_ledger("user", user_text)
    dependencies.handle_user_text(
        user_text=user_text,
        confidence_hint=confidence_hint,
        interaction_id=interaction_id,
        replay_mode=replay_mode,
        overrides=overrides,
        audio_data=audio_data,
    )
