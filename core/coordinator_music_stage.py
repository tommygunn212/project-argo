"""Music routing stage for the classic coordinator."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable

from core.intent_parser import IntentType
from core.music_player import get_music_player
from core.music_status import query_music_status


@dataclass(frozen=True)
class MusicStageResult:
    """Outcome of deterministic music routing."""

    routed: bool
    return_interaction: bool = False
    interaction_result: bool = True
    output_produced: bool = False
    response_text: str = ""
    is_music_iteration: bool = False


def stop_active_music_for_phrase(
    coordinator: Any,
    text: str,
    finalize_watchdog: Callable[[], None],
) -> bool:
    """Stop active music when a general stop phrase arrives."""
    stop_terms = {"stop", "pause", "cancel", "shut up", "shutup", "shut-up"}
    if not any(term in text.lower() for term in stop_terms):
        return False

    music_player = get_music_player()
    if not music_player.is_playing():
        return False

    coordinator.logger.info("[ARGO] Active music detected")
    music_player.stop()
    coordinator._last_utterance_time = time.time()
    finalize_watchdog()
    return True


def dispatch_music_stage(
    coordinator: Any,
    intent: Any,
    mark_output: Callable[[], None],
    finalize_watchdog: Callable[[], None],
) -> MusicStageResult:
    """Route music intents while preserving audio and watchdog ownership."""
    if intent.intent_type == IntentType.MUSIC_STOP:
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] STOP command: Stopping music"
        )
        music_player = get_music_player()
        blocked = music_player.preflight()
        if blocked:
            message = "Music library not indexed yet."
            coordinator.logger.info(
                f"[Iteration {coordinator.interaction_count}] "
                f"Music blocked: {blocked.get('reason')}"
            )
            if coordinator.runtime_overrides.get("tts_enabled", True):
                coordinator._safe_speak(
                    message, interaction_id=coordinator.interaction_id
                )
            coordinator.release_audio("MUSIC")
            coordinator.current_probe.mark("llm_end")
            finalize_watchdog()
            coordinator._last_utterance_time = time.time()
            return MusicStageResult(True, return_interaction=True)

        music_player.stop()
        try:
            coordinator.release_audio("MUSIC")
        except Exception:
            pass
        coordinator._safe_speak(
            "Stopped.", interaction_id=coordinator.interaction_id
        )
        mark_output()
        coordinator.current_probe.mark("llm_end")
        finalize_watchdog()
        coordinator._last_utterance_time = time.time()
        return MusicStageResult(
            True, return_interaction=True, output_produced=True
        )

    if intent.intent_type == IntentType.MUSIC_NEXT:
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] "
            "NEXT command: Playing next track"
        )
        music_player = get_music_player()
        playback_started = music_player.play_next(coordinator.sink)
        if not playback_started:
            coordinator._safe_speak(
                "No music playing.", interaction_id=coordinator.interaction_id
            )
            coordinator.logger.warning(
                f"[Iteration {coordinator.interaction_count}] "
                "NEXT failed: no playback mode"
            )
        else:
            coordinator.logger.info(
                f"[Iteration {coordinator.interaction_count}] NEXT: Started playback"
            )
            coordinator._monitor_music_interrupt(music_player)
        mark_output()
        coordinator.current_probe.mark("llm_end")
        finalize_watchdog()
        coordinator._last_utterance_time = time.time()
        return MusicStageResult(
            True, return_interaction=True, output_produced=True
        )

    if intent.intent_type == IntentType.MUSIC_STATUS:
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] "
            "STATUS query: What's playing"
        )
        status = query_music_status()
        coordinator._safe_speak(status, interaction_id=coordinator.interaction_id)
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] STATUS response: {status}"
        )
        mark_output()
        coordinator.current_probe.mark("llm_end")
        finalize_watchdog()
        coordinator._last_utterance_time = time.time()
        return MusicStageResult(
            True, return_interaction=True, output_produced=True
        )

    if intent.intent_type != IntentType.MUSIC:
        return MusicStageResult(False)

    if not coordinator.runtime_overrides.get("music_enabled", True):
        message = "Music is disabled."
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] {message}"
        )
        if coordinator.runtime_overrides.get("tts_enabled", True):
            coordinator._safe_speak(
                message, interaction_id=coordinator.interaction_id
            )
        coordinator.current_probe.mark("llm_end")
        return MusicStageResult(True, return_interaction=True)

    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] "
        "Music command - not counting as interaction turn"
    )
    music_player = get_music_player()
    try:
        coordinator.acquire_audio("MUSIC")
    except Exception as exc:
        coordinator.logger.warning(
            f"[Iteration {coordinator.interaction_count}] Music blocked: {exc}"
        )
        if coordinator.runtime_overrides.get("tts_enabled", True):
            coordinator._safe_speak(
                "Audio busy. Try again.", interaction_id=coordinator.interaction_id
            )
        coordinator.current_probe.mark("llm_end")
        return MusicStageResult(True, return_interaction=True)

    playback_started = False
    error_message = ""
    artist = getattr(intent, "artist", None)
    title = getattr(intent, "title", None)
    do_not_try_genre_lookup = bool(title)
    explicit_genre = bool(getattr(intent, "explicit_genre", False))

    if (
        getattr(intent, "is_generic_play", False)
        and not artist
        and not title
        and not intent.keyword
    ):
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] "
            "Music route: RANDOM (generic play)"
        )
        playback_started = music_player.play_random(None)
        if not playback_started:
            error_message = "Your music library is empty or unavailable."

    if title:
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] Music title: '{title}'"
        )
        if not playback_started:
            playback_started = music_player.play_by_song(title, None)
            if playback_started:
                coordinator.logger.info(
                    f"[Iteration {coordinator.interaction_count}] Music route: SONG match"
                )
            elif not artist:
                playback_started = music_player.play_by_artist(title, None)
                if playback_started:
                    coordinator.logger.info(
                        f"[Iteration {coordinator.interaction_count}] "
                        "Music route: ARTIST fallback (title-only)"
                    )

    if not playback_started and artist:
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] Music artist: '{artist}'"
        )
        playback_started = music_player.play_by_artist(artist, None)
        if playback_started:
            coordinator.logger.info(
                f"[Iteration {coordinator.interaction_count}] Music route: ARTIST match"
            )

    if not playback_started and intent.keyword:
        keyword = intent.keyword
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] Music keyword: '{keyword}'"
        )
        if explicit_genre and not do_not_try_genre_lookup:
            playback_started = music_player.play_by_genre(keyword, None)
        if playback_started:
            coordinator.logger.info(
                f"[Iteration {coordinator.interaction_count}] Music route: GENRE match"
            )
        if not playback_started:
            playback_started = music_player.play_by_keyword(keyword, None)
            if playback_started:
                coordinator.logger.info(
                    f"[Iteration {coordinator.interaction_count}] "
                    "Music route: KEYWORD match"
                )
        if not playback_started:
            error_message = f"No music found for '{keyword}'."
            coordinator.logger.warning(
                f"[Iteration {coordinator.interaction_count}] "
                f"Music failed: {error_message}"
            )
    else:
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] "
            "Music route: RANDOM (no keyword)"
        )
        playback_started = music_player.play_random(None)
        if not playback_started:
            error_message = "No music available."
            coordinator.logger.warning(
                f"[Iteration {coordinator.interaction_count}] "
                f"Music failed: {error_message}"
            )

    if not playback_started and title:
        setattr(intent, "unresolved", True)
        coordinator._safe_speak(
            "I can’t find that track in your library.",
            interaction_id=coordinator.interaction_id,
        )
        mark_output()
        coordinator.release_audio("MUSIC")
        coordinator.current_probe.mark("llm_end")
        finalize_watchdog()
        coordinator._last_utterance_time = time.time()
        return MusicStageResult(
            True,
            return_interaction=True,
            output_produced=True,
            is_music_iteration=True,
        )

    output_produced = False
    if error_message and not playback_started:
        coordinator._safe_speak(
            error_message, interaction_id=coordinator.interaction_id
        )
        mark_output()
        output_produced = True

    if playback_started:
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] "
            "Monitoring for interrupt during music..."
        )
        coordinator._monitor_music_interrupt(music_player)
        mark_output()
        output_produced = True
    else:
        coordinator.release_audio("MUSIC")

    coordinator.current_probe.mark("llm_end")
    return MusicStageResult(
        True,
        output_produced=output_produced,
        response_text="",
        is_music_iteration=True,
    )
