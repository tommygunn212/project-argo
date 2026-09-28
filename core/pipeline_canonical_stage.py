"""Canonical-answer interception stage for the classic pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.canonical_answers import get_canonical_answer


@dataclass(frozen=True)
class CanonicalStageResult:
    handled: bool
    topic: str | None
    matched: set[str]


def _finish(
    pipeline: Any,
    response: str,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
    *,
    deterministic: bool,
) -> None:
    pipeline.broadcast("log", f"Argo: {response}")
    pipeline._append_convo_ledger("argo", response)
    if not pipeline.stop_signal.is_set() and not replay_mode:
        if deterministic:
            tts_text = pipeline._sanitize_tts_text(
                response, enforce_confidence=False, deterministic=True
            )
        else:
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


def run_canonical_stage(
    pipeline: Any,
    user_text: str,
    stt_confidence: float,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> CanonicalStageResult:
    """Intercept deterministic answers and return classification state."""
    topic, matched = pipeline._classify_canonical_topic(user_text)
    matched = set(matched)
    if topic == "SYSTEM_HEALTH":
        pipeline.logger.info(
            f"[CANONICAL] SYSTEM_HEALTH matched keywords: {sorted(matched)} | LLM BYPASSED"
        )
        if pipeline._respond_with_system_health(
            user_text, None, interaction_id, replay_mode, overrides
        ):
            return CanonicalStageResult(True, topic, matched)
        topic = None
    if topic == "ARGO_IDENTITY":
        pipeline.logger.info(
            f"[CANONICAL] ARGO_IDENTITY matched keywords: {sorted(matched)} | "
            "routing to LLM with persona"
        )
        topic = None
    if topic == "ARGO_GOVERNANCE":
        pipeline.logger.info(
            f"[CANONICAL] ARGO_GOVERNANCE matched keywords: {sorted(matched)} | LLM BYPASSED"
        )
        if pipeline._respond_with_argo_governance(
            None, interaction_id, replay_mode, overrides
        ):
            return CanonicalStageResult(True, topic, matched)
        topic = None
    if topic:
        pipeline._session_flags["clarification_asked"] = False

    if pipeline._is_convo_recall_request(user_text):
        response = pipeline._handle_convo_recall()
        _finish(
            pipeline,
            response,
            interaction_id,
            replay_mode,
            overrides,
            deterministic=False,
        )
        return CanonicalStageResult(True, topic, matched)

    if topic and topic not in {"SYSTEM_HEALTH", "COUNT"}:
        phrase_match = any(" " in match for match in matched)
        pipeline.logger.debug(
            "[STT] confidence_used=%s phrase_match=%s",
            stt_confidence,
            phrase_match,
        )
        if not phrase_match and stt_confidence < 0.5:
            pipeline.logger.info(
                f"[CANONICAL] Low confidence ({stt_confidence:.2f}) "
                "without phrase match; deferring to LLM"
            )
            topic = None

    if topic == "COUNT":
        response = pipeline._build_count_response(user_text)
        pipeline.logger.info(
            f"[CANONICAL] Intercepted topic: COUNT | Matched: {sorted(matched)} | "
            "LLM BYPASSED"
        )
        _finish(
            pipeline,
            response,
            interaction_id,
            replay_mode,
            overrides,
            deterministic=True,
        )
        return CanonicalStageResult(True, topic, matched)

    if topic:
        answer = get_canonical_answer(topic) or ""
        pipeline.logger.info(
            f"[CANONICAL] Intercepted topic: {topic} | Matched: {sorted(matched)} | "
            "LLM BYPASSED"
        )
        _finish(
            pipeline,
            answer,
            interaction_id,
            replay_mode,
            overrides,
            deterministic=True,
        )
        return CanonicalStageResult(True, topic, matched)

    return CanonicalStageResult(False, topic, matched)
