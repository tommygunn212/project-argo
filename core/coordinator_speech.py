"""Owned, feedback-safe speech playback for the classic coordinator."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CoordinatorSpeechDependencies:
    logger: Any
    pause_input: Callable[[], None]
    resume_input: Callable[[], None]
    acquire_audio: Callable[[str], None]
    release_audio: Callable[[str], None]
    speak: Callable[..., None]
    get_interaction_id: Callable[[], Any]
    clear_speaking: Callable[[], None]


def speak_without_interrupt_detection(
    dependencies: CoordinatorSpeechDependencies,
    response_text: str,
) -> None:
    """Speak while input is paused, releasing only audio successfully acquired."""

    input_paused = False
    try:
        dependencies.logger.info(
            "[TTS] Speaking response (interrupts disabled during playback)..."
        )
        try:
            dependencies.pause_input()
            input_paused = True
        except Exception as exc:
            dependencies.logger.warning(f"[TTS] Failed to pause input: {exc}")

        try:
            try:
                dependencies.acquire_audio("TTS")
            except Exception as exc:
                dependencies.logger.warning(f"[TTS] Audio ownership denied: {exc}")
                return
            try:
                dependencies.speak(
                    response_text,
                    interaction_id=dependencies.get_interaction_id(),
                )
            finally:
                dependencies.release_audio("TTS")
            dependencies.logger.info("[TTS] Response finished")
        except Exception as exc:
            dependencies.logger.error(f"[TTS] Error during sink.speak(): {exc}")
            raise
        finally:
            if input_paused:
                try:
                    dependencies.resume_input()
                except Exception as exc:
                    dependencies.logger.warning(
                        f"[TTS] Failed to resume input: {exc}"
                    )
    except Exception as exc:
        dependencies.logger.error(
            f"[TTS] Fatal error during speech: {exc}", exc_info=True
        )
    finally:
        try:
            dependencies.clear_speaking()
        except Exception:
            pass
