"""Music-volume command handling for the classic conversation pipeline."""

from __future__ import annotations

import re
from typing import Any, Callable


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


def dispatch_music_volume(
    pipeline: Any,
    user_text: str,
    request_kind: str,
    low_confidence_audio: bool,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> bool:
    """Handle an exact music-volume command, or return ``False`` to fall through."""
    user_text_lower = user_text.lower().strip()
    if not any(term in user_text_lower for term in {"music", "song", "player"}):
        return False

    from core.music_player import (
        adjust_volume_percent,
        get_volume_percent,
        set_volume_percent,
    )

    volume_patterns: list[tuple[str, Callable[[re.Match[str]], Any]]] = [
        (r"(?:music )?volume (\d{1,3})%?", lambda m: set_volume_percent(int(m.group(1)))),
        (r"set volume to (\d{1,3})%?", lambda m: set_volume_percent(int(m.group(1)))),
        (r"volume up (\d{1,3})%?", lambda m: adjust_volume_percent(int(m.group(1)))),
        (r"volume down (\d{1,3})%?", lambda m: adjust_volume_percent(-int(m.group(1)))),
        (r"volume up", lambda _m: adjust_volume_percent(10)),
        (r"volume down", lambda _m: adjust_volume_percent(-10)),
        (r"what is the volume", lambda _m: None),
        (r"current volume", lambda _m: None),
    ]
    user_text_clean = re.sub(r"[^\w\s%]", " ", user_text_lower)
    user_text_clean = re.sub(r"\s+", " ", user_text_clean).strip()
    is_imperative = bool(re.match(r"^(music\s+)?volume\b", user_text_clean))
    if user_text_lower.endswith("?"):
        is_imperative = False
    if re.search(
        r"\b(would|could|can|should|might|maybe|perhaps|possibly)\b",
        user_text_clean,
    ):
        is_imperative = False
    if re.search(r"\bwhat happens if\b|\bwhat if\b", user_text_clean):
        is_imperative = False

    for pattern, action in volume_patterns:
        match = re.fullmatch(pattern, user_text_clean)
        if match is None:
            continue

        is_status_query = pattern in {"what is the volume", "current volume"}
        effective_kind = "ACTION" if is_imperative else request_kind
        if effective_kind != "ACTION" and not is_status_query:
            response = "I can adjust volume. Say it as a command to execute."
        elif low_confidence_audio and effective_kind == "ACTION" and not is_status_query:
            response = (
                "I heard that, but the audio was unclear. "
                "Please repeat the volume command."
            )
        elif not is_status_query and not (
            pipeline._is_executable_command(user_text) or is_imperative
        ):
            response = "I can adjust volume. Say it as a direct command."
        else:
            allowed, reason = pipeline._evaluate_gates(
                "music_playback", "music_player", interaction_id
            )
            if not allowed:
                response = f"Action blocked by policy ({reason})."
                pipeline.logger.info(f"[GATE] {response}")
            elif is_status_query:
                response = f"Music volume: {get_volume_percent()}%"
            else:
                action(match)
                response = f"Music volume set to {get_volume_percent()}%"
            if allowed:
                pipeline.logger.info(f"[ARGO] {response}")

        _finish(pipeline, response, interaction_id, replay_mode, overrides)
        return True

    return False
