"""System-information intent handling for the classic pipeline."""

from __future__ import annotations

from typing import Any

from core.intent_parser import IntentType
from system_profile import get_gpu_profile, get_system_profile


def _build_response(intent: Any, profile: dict[str, Any], gpus: list[dict[str, Any]]) -> str:
    subintent = getattr(intent, "subintent", None)
    if subintent == "memory":
        ram_gb = profile.get("ram_gb") if profile else None
        return (
            f"Your system has {ram_gb} gigabytes of memory."
            if ram_gb is not None
            else "Hardware information unavailable."
        )
    if subintent == "cpu":
        cpu_name = profile.get("cpu") if profile else None
        return (
            f"Your CPU is a {cpu_name}."
            if cpu_name
            else "Hardware information unavailable."
        )
    if subintent == "gpu":
        return f"Your GPU is {gpus[0].get('name')}." if gpus else "No GPU detected."
    if subintent == "os":
        os_name = profile.get("os") if profile else None
        return (
            f"You are running {os_name}."
            if os_name
            else "Hardware information unavailable."
        )
    if subintent == "motherboard":
        board = profile.get("motherboard") if profile else None
        return (
            f"Your motherboard is {board}."
            if board
            else "Hardware information unavailable."
        )
    return "Hardware information unavailable."


def _finish(
    pipeline: Any,
    response: str,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> None:
    pipeline.broadcast("log", f"Argo: {response}")
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


def dispatch_system_info(
    pipeline: Any,
    intent: Any,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> bool:
    """Handle SYSTEM_INFO, returning False for every other intent."""
    if intent is None or intent.intent_type != IntentType.SYSTEM_INFO:
        return False

    allowed, reason = pipeline._evaluate_gates(
        "system_health", "system_health", interaction_id
    )
    if allowed:
        response = _build_response(intent, get_system_profile(), get_gpu_profile())
    else:
        response = f"System information access blocked by policy ({reason})."
    _finish(pipeline, response, interaction_id, replay_mode, overrides)
    return True
