"""Ordered text-routing stages for the classic pipeline."""

from __future__ import annotations

from typing import Any, Protocol

from core.pipeline_canonical_stage import run_canonical_stage
from core.pipeline_confidence_gate import apply_confidence_gate
from core.pipeline_conversation_gates import dispatch_conversation_gate
from core.pipeline_intent_stage import prepare_intent_stage
from core.pipeline_platform_dispatch import dispatch_early_status
from core.pipeline_pre_intent_gates import dispatch_pre_intent_gate
from core.pipeline_prepared_dispatch import PreparedDispatch, dispatch_prepared_intent


class PipelineTextRouterHost(Protocol):
    """Pipeline state required to route already-transcribed text."""

    logger: Any
    strict_lab_mode: bool
    _current_stt_confidence: float
    _intent_parser: Any

    def _deliver_canonical_response(self, *args: Any, **kwargs: Any) -> bool: ...
    def _classify_request_kind(self, user_text: str) -> str: ...


def route_user_text(
    pipeline: PipelineTextRouterHost,
    user_text: str,
    confidence_hint: float,
    interaction_id: str = "",
    replay_mode: bool = False,
    overrides: dict | None = None,
    audio_data: Any = None,
) -> None:
    """Run text through the established stage precedence."""
    user_text = (user_text or "").strip()
    repair_service = getattr(pipeline, "repair_service", None)
    if repair_service is not None and not replay_mode:
        repair_result = repair_service.handle_text(user_text)
        if repair_result is not None:
            pipeline._deliver_canonical_response(
                repair_result["message"],
                interaction_id,
                replay_mode,
                overrides,
                enforce_confidence=False,
                force_tts=True,
            )
            return

    try:
        stt_confidence = max(0.0, min(1.0, float(confidence_hint)))
    except Exception:
        stt_confidence = 0.0
    pipeline._current_stt_confidence = stt_confidence

    try:
        early_intent = pipeline._intent_parser.parse(user_text)
    except Exception:
        early_intent = None
    if dispatch_early_status(
        pipeline,
        early_intent,
        user_text,
        interaction_id,
        replay_mode,
        overrides,
    ):
        return
    pipeline.logger.info(
        "[STT] text_received conf_hint=%.2f strict_lab_mode=%s",
        stt_confidence,
        pipeline.strict_lab_mode,
    )
    if dispatch_conversation_gate(
        pipeline, user_text, interaction_id, replay_mode, overrides
    ):
        return

    request_kind = pipeline._classify_request_kind(user_text)
    confidence_result = apply_confidence_gate(
        pipeline, user_text, stt_confidence, early_intent, interaction_id
    )
    early_intent = confidence_result.intent
    if confidence_result.handled:
        return

    canonical_result = run_canonical_stage(
        pipeline,
        user_text,
        stt_confidence,
        interaction_id,
        replay_mode,
        overrides,
    )
    if canonical_result.handled:
        return
    if dispatch_pre_intent_gate(
        pipeline,
        user_text,
        request_kind,
        canonical_result.topic,
        interaction_id,
        replay_mode,
        overrides,
    ):
        return

    intent_result = prepare_intent_stage(
        pipeline,
        early_intent,
        user_text,
        canonical_result.topic,
        canonical_result.matched,
        stt_confidence,
        interaction_id,
        replay_mode,
        overrides,
    )
    if intent_result.handled:
        return
    dispatch_prepared_intent(
        pipeline,
        PreparedDispatch(
            intent=intent_result.intent,
            user_text=user_text,
            request_kind=intent_result.request_kind,
            safe_utterance=intent_result.safe_utterance,
            low_confidence_audio=intent_result.low_confidence_audio,
            stt_confidence=stt_confidence,
            interaction_id=interaction_id,
            replay_mode=replay_mode,
            overrides=overrides,
            audio_data=audio_data,
        ),
    )
