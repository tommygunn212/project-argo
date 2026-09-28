"""Canonical response delivery for the classic pipeline.

This module owns the response-finalization policy while the pipeline keeps a
small compatibility facade.  Dependencies are explicit so delivery does not
need the full pipeline object.
"""

from dataclasses import dataclass
from typing import Any, Callable


TTS_ALLOWED_REASON_DETERMINISTIC = "DETERMINISTIC_CONFIDENCE_BYPASS"


@dataclass(frozen=True)
class ResponseDeliveryDependencies:
    logger: Any
    broadcast: Callable[[str, str], None]
    sanitize_tts_text: Callable[..., str]
    speak: Callable[..., None]
    transition_state: Callable[..., None]
    record_timeline: Callable[..., None]
    apply_persona: Callable[[str, Any, str], str]
    set_pending_barge_in_suppression: Callable[[float], None]


def deliver_canonical_response(
    dependencies: ResponseDeliveryDependencies,
    *,
    message: str,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict | None,
    persona_name: str,
    response_type: Any,
    stop_requested: bool,
    tts_enabled: bool,
    personal_mode_min_confidence: float,
    edge_tts: Any = None,
    enforce_confidence: bool = True,
    force_tts: bool = False,
    suppress_barge_in_seconds: float | None = None,
    deterministic: bool = True,
    stt_conf: float | None = None,
    intent_type: str | None = None,
) -> bool:
    """Format, emit, optionally speak, and finalize one canonical response."""

    message = dependencies.apply_persona(message, response_type, persona_name)

    if (
        deterministic
        and stt_conf is not None
        and stt_conf < personal_mode_min_confidence
    ):
        dependencies.logger.info(
            f"[TTS] Allowed despite low STT confidence "
            f"(reason={TTS_ALLOWED_REASON_DETERMINISTIC}, "
            f"confidence={stt_conf:.2f}, intent={intent_type or 'unknown'})"
        )

    dependencies.broadcast("log", f"Argo: {message}")
    if not stop_requested and not replay_mode:
        tts_text = dependencies.sanitize_tts_text(
            message,
            enforce_confidence=enforce_confidence,
            deterministic=deterministic,
        )
        tts_override = (overrides or {}).get("suppress_tts", False)
        if force_tts:
            tts_override = False
        if tts_override:
            dependencies.logger.info("[TTS] Suppressed for next interaction override")
        elif tts_text and (force_tts or tts_enabled):
            if suppress_barge_in_seconds:
                dependencies.set_pending_barge_in_suppression(
                    suppress_barge_in_seconds
                )
                if edge_tts is not None and hasattr(edge_tts, "suppress_interrupt"):
                    try:
                        edge_tts.suppress_interrupt(suppress_barge_in_seconds)
                    except Exception:
                        pass
            dependencies.speak(tts_text, interaction_id=interaction_id)

    dependencies.transition_state(
        "LISTENING", interaction_id=interaction_id, source="audio"
    )
    dependencies.logger.info("--- Interaction Complete ---")
    dependencies.record_timeline(
        "INTERACTION_END", stage="pipeline", interaction_id=interaction_id
    )
    return True
