"""Classic non-streaming TTS playback behind explicit dependencies."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable


@dataclass(frozen=True)
class SpeechDependencies:
    logger: Any
    tts_enabled: bool
    current_state: str
    current_voice_key: str
    tts_engine: str
    tts_model: str
    tts_instructions: str
    edge_voices: dict[str, str]
    openai_voices: dict[str, str]
    output_device: int | None
    stop_signal: Any
    acquire_audio: Callable[..., None]
    release_audio: Callable[..., None]
    transition_state: Callable[..., None]
    record_timeline: Callable[..., None]
    record_event: Callable[..., None]
    play_error_cue: Callable[[str], None]
    broadcast_audio_level: Callable[[float], None]
    set_speaking: Callable[[bool], None]
    set_finished_at: Callable[[float], None]
    get_edge_tts: Callable[[], Any]
    set_edge_tts: Callable[[Any], None]
    get_openai_tts: Callable[[], Any]
    set_openai_tts: Callable[[Any], None]
    get_barge_in_suppression: Callable[[], Any]
    clear_barge_in_suppression: Callable[[], None]


def speak_text(
    dependencies: SpeechDependencies,
    text: str,
    *,
    interaction_id: str = "",
    force_tts: bool = False,
) -> None:
    """Speak one complete response while preserving audio ownership."""
    if not dependencies.tts_enabled and not force_tts:
        dependencies.logger.info("[TTS] Disabled by runtime override")
        return

    dependencies.logger.info(
        f"[TTS] Speaking with {dependencies.current_voice_key} "
        f"(engine={dependencies.tts_engine})..."
    )
    if dependencies.current_state == "TRANSCRIBING":
        dependencies.transition_state(
            "THINKING", interaction_id=interaction_id, source="tts"
        )
    dependencies.transition_state(
        "SPEAKING", interaction_id=interaction_id, source="tts"
    )
    dependencies.stop_signal.clear()
    dependencies.set_speaking(True)
    dependencies.record_timeline(
        "TTS_START", stage="tts", interaction_id=interaction_id
    )

    audio_acquired = False
    try:
        try:
            dependencies.acquire_audio("TTS", interaction_id=interaction_id)
            audio_acquired = True
        except Exception as exc:
            dependencies.logger.error(f"[TTS] Audio ownership error: {exc}")
            dependencies.record_event(
                "TTS_AUDIO_CONTESTED",
                stage="audio",
                interaction_id=interaction_id,
            )
            dependencies.play_error_cue(interaction_id)
            return

        if dependencies.tts_engine == "openai":
            tts = dependencies.get_openai_tts()
            if tts is None:
                from core.openai_tts import OpenAIRealtimeTTS

                voice = dependencies.openai_voices.get(
                    dependencies.current_voice_key, "nova"
                )
                tts = OpenAIRealtimeTTS(
                    voice=voice,
                    model=dependencies.tts_model,
                    output_device=dependencies.output_device,
                    on_audio_level=dependencies.broadcast_audio_level,
                )
                tts._instructions = dependencies.tts_instructions
                dependencies.set_openai_tts(tts)
            suppression = dependencies.get_barge_in_suppression()
            if suppression:
                try:
                    tts.suppress_interrupt(suppression)
                except Exception:
                    pass
                dependencies.clear_barge_in_suppression()
            tts.speak(text)
        else:
            tts = dependencies.get_edge_tts()
            if tts is None:
                from core.output_sink import EdgeTTSOutputSink

                tts = EdgeTTSOutputSink(
                    voice=dependencies.edge_voices.get(
                        dependencies.current_voice_key, "en-US-AriaNeural"
                    )
                )
                dependencies.set_edge_tts(tts)
            suppression = dependencies.get_barge_in_suppression()
            if suppression and hasattr(tts, "suppress_interrupt"):
                try:
                    tts.suppress_interrupt(suppression)
                except Exception:
                    pass
                dependencies.clear_barge_in_suppression()
            tts.speak(text)
    except Exception as exc:
        dependencies.logger.error(f"[TTS] Error: {exc}")
        dependencies.play_error_cue(interaction_id)
    finally:
        if audio_acquired:
            try:
                dependencies.release_audio("TTS", interaction_id=interaction_id)
            except Exception as exc:
                dependencies.logger.error(
                    f"[TTS] Exception during audio.release_audio: {exc}"
                )
        dependencies.set_speaking(False)
        dependencies.set_finished_at(time.time())
        dependencies.record_timeline(
            "TTS_DONE", stage="tts", interaction_id=interaction_id
        )
