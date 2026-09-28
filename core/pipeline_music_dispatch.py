"""Music playback intent handling for the classic conversation pipeline."""

from __future__ import annotations

from typing import Any, Optional

from core.intent_parser import IntentType
from core.music_player import get_music_player
from core.music_status import query_music_status


def dispatch_music_intent(
    pipeline: Any,
    intent: Any,
    user_text: str,
    request_kind: str,
    low_confidence_audio: bool,
    stt_conf: float,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> bool:
    """Handle a parsed music intent, or return False to fall through."""
    if intent and intent.intent_type in {
        IntentType.MUSIC,
        IntentType.MUSIC_STOP,
        IntentType.MUSIC_NEXT,
        IntentType.MUSIC_STATUS,
    }:
        pipeline.logger.info(
            "[MUSIC] intent=%s request_kind=%s entered handler",
            intent.intent_type if intent else None,
            request_kind,
        )
        if request_kind != "ACTION" and intent.intent_type in {IntentType.MUSIC, IntentType.MUSIC_STOP, IntentType.MUSIC_NEXT}:
            pipeline.logger.info(
                "[MUSIC GUARD] guard=non_action intent=%s request_kind=%s",
                intent.intent_type,
                request_kind,
            )
            response = "I can do that. Say it as a command to execute."
            pipeline.broadcast("log", f"Argo: {response}")
            if not pipeline.stop_signal.is_set() and not replay_mode:
                tts_text = pipeline._sanitize_tts_text(response)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    pipeline.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    pipeline.speak(tts_text, interaction_id=interaction_id)
            pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            pipeline.logger.info("--- Interaction Complete ---")
            pipeline._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
            return True
        if (
            low_confidence_audio
            and request_kind == "ACTION"
            and intent.intent_type in {IntentType.MUSIC, IntentType.MUSIC_STOP, IntentType.MUSIC_NEXT}
            and not pipeline._allow_low_conf_music_command(intent, user_text)
        ):
            pipeline.logger.info(
                "[MUSIC GUARD] guard=low_confidence intent=%s request_kind=%s stt_conf=%.2f",
                intent.intent_type,
                request_kind,
                stt_conf,
            )
            response = "I heard a music control, but the audio was unclear. Please repeat the command."
            pipeline.broadcast("log", f"Argo: {response}")
            if not pipeline.stop_signal.is_set() and not replay_mode:
                tts_text = pipeline._sanitize_tts_text(response)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    pipeline.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    pipeline.speak(tts_text, interaction_id=interaction_id)
            pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            pipeline.logger.info("--- Interaction Complete ---")
            pipeline._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
            return True
        if intent.intent_type in {IntentType.MUSIC, IntentType.MUSIC_STOP, IntentType.MUSIC_NEXT}:
            executable = pipeline._is_executable_command(user_text)
            if intent.intent_type == IntentType.MUSIC and user_text.lower().startswith("play"):
                executable = True
            if not executable:
                pipeline.logger.info(
                    "[MUSIC GUARD] guard=non_executable intent=%s request_kind=%s text=\"%s\"",
                    intent.intent_type,
                    request_kind,
                    user_text,
                )
                response = "I can do that. Say it as a direct command."
                pipeline.broadcast("log", f"Argo: {response}")
                if not pipeline.stop_signal.is_set() and not replay_mode:
                    tts_text = pipeline._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        pipeline.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        pipeline.speak(tts_text, interaction_id=interaction_id)
                pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                pipeline.logger.info("--- Interaction Complete ---")
                pipeline._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return True
        allowed, reason = pipeline._evaluate_gates("music_playback", "music_player", interaction_id)
        if not allowed:
            pipeline.logger.info(
                "[MUSIC GUARD] guard=policy_block intent=%s request_kind=%s reason=%s",
                intent.intent_type,
                request_kind,
                reason,
            )
            response = f"Action blocked by policy ({reason})."
            pipeline.logger.info(f"[GATE] {response}")
            if pipeline.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                pipeline.speak(response, interaction_id=interaction_id)
            pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            return True
        if not pipeline.runtime_overrides.get("music_enabled", True):
            pipeline.logger.info(
                "[MUSIC GUARD] guard=music_disabled intent=%s request_kind=%s",
                intent.intent_type,
                request_kind,
            )
            msg = "Music is disabled."
            if pipeline.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                pipeline.speak(msg, interaction_id=interaction_id)
            pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            return True

        music_player = get_music_player()
        blocked = music_player.preflight()
        if blocked:
            pipeline.logger.info(
                "[MUSIC GUARD] guard=preflight intent=%s request_kind=%s message=%s",
                intent.intent_type,
                request_kind,
                blocked,
            )
            if pipeline.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                pipeline.speak("Music library not indexed yet.", interaction_id=interaction_id)
            pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            return True
        playback_started = False
        error_message = ""

        if intent.intent_type == IntentType.MUSIC_STOP:
            music_player.stop()
            if pipeline.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                pipeline.speak("Stopped.", interaction_id=interaction_id)
            pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            return True

        if intent.intent_type == IntentType.MUSIC_NEXT:
            playback_started = music_player.play_next(None)
            if not playback_started:
                error_message = "No music playing."
            title = None  # Not applicable for MUSIC_NEXT

        elif intent.intent_type == IntentType.MUSIC_STATUS:
            status = query_music_status()
            if pipeline.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                pipeline.speak(status, interaction_id=interaction_id)
            pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            return True

        else:
            artist = getattr(intent, "artist", None)
            title: Optional[str] = getattr(intent, "title", None)
            do_not_try_genre_lookup = bool(title)
            explicit_genre = bool(getattr(intent, "explicit_genre", False))
            if getattr(intent, "is_generic_play", False) and not artist and not title and not getattr(intent, "keyword", None):
                playback_started = music_player.play_random(None)
                if not playback_started:
                    error_message = "Your music library is empty or unavailable."
                pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                return True
            if title:
                playback_started = music_player.play_by_song(title, None)
                if not playback_started and not artist:
                    playback_started = music_player.play_by_artist(title, None)
            if not playback_started and artist:
                playback_started = music_player.play_by_artist(artist, None)
            if not playback_started and getattr(intent, "keyword", None):
                keyword = intent.keyword
                if keyword and explicit_genre and not do_not_try_genre_lookup:
                    playback_started = music_player.play_by_genre(keyword, None)
                if not playback_started and keyword:
                    playback_started = music_player.play_by_keyword(keyword, None)
                if not playback_started:
                    error_message = f"No music found for '{keyword}'."
            if not playback_started and not artist and not title and not getattr(intent, "keyword", None):
                playback_started = music_player.play_random(None)
                if not playback_started:
                    error_message = "No music available."

        if intent.intent_type == IntentType.MUSIC and not playback_started and title:
            setattr(intent, "unresolved", True)
            if pipeline.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                pipeline.speak("I can’t find that track in your library.", interaction_id=interaction_id)
            pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            return True

        if error_message and pipeline.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
            pipeline.speak(error_message, interaction_id=interaction_id)

        pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
        return True

    return False
