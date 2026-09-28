"""Ordered dispatch for a fully prepared classic-pipeline intent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.pipeline_domain_dispatch import dispatch_domain_intent
from core.pipeline_llm_stage import run_llm_stage
from core.pipeline_music_dispatch import dispatch_music_intent
from core.pipeline_music_volume import dispatch_music_volume
from core.pipeline_platform_dispatch import dispatch_platform_intent
from core.pipeline_restricted_fallback import block_restricted_llm_fallback
from core.pipeline_special_dispatch import dispatch_special_intent
from core.pipeline_system_info import dispatch_system_info


@dataclass(frozen=True)
class PreparedDispatch:
    intent: Any
    user_text: str
    request_kind: str
    safe_utterance: bool
    low_confidence_audio: bool
    stt_confidence: float
    interaction_id: str
    replay_mode: bool
    overrides: dict[str, Any] | None
    audio_data: Any = None


def dispatch_prepared_intent(host: object, request: PreparedDispatch) -> None:
    """Run prepared-intent stages in precedence order, stopping at first match."""
    common = (request.interaction_id, request.replay_mode, request.overrides)
    if dispatch_music_volume(
        host,
        request.user_text,
        request.request_kind,
        request.low_confidence_audio,
        *common,
    ):
        return
    if dispatch_music_intent(
        host,
        request.intent,
        request.user_text,
        request.request_kind,
        request.low_confidence_audio,
        request.stt_confidence,
        *common,
    ):
        return
    if dispatch_platform_intent(
        host,
        request.intent,
        request.user_text,
        request.stt_confidence,
        *common,
    ):
        return
    if dispatch_special_intent(host, request.intent, request.user_text, *common):
        return
    if dispatch_domain_intent(host, request.intent, request.user_text, *common):
        return
    if dispatch_system_info(host, request.intent, *common):
        return
    if block_restricted_llm_fallback(
        host,
        request.intent,
        request.user_text,
        request.safe_utterance,
        *common,
    ):
        return
    run_llm_stage(
        host,
        request.intent,
        request.user_text,
        request.request_kind,
        *common,
        request.audio_data,
    )
