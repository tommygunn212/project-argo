"""Wake-triggered recording and command dispatch for the legacy wrapper."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class WakeInteractionRuntime:
    state_machine: Any
    command_parser: Any
    request_factory: Callable[..., Any]
    load_voice_input: Callable[[], tuple[Callable[[], Any], Callable[[Any], str]]]
    logger: Any


def run_wake_interaction(runtime: WakeInteractionRuntime) -> None:
    """Wake if needed, capture one utterance, and dispatch its wake request."""

    current_state = runtime.state_machine.current_state
    runtime.logger.warning("WAKE WORD DETECTED — FORCING RECORD")

    if current_state not in ["SLEEP", "LISTENING"]:
        runtime.logger.debug(f"Wake-word ignored: in {current_state} state")
        return

    if current_state == "SLEEP":
        runtime.logger.info(
            "Wake-word detected in SLEEP - transitioning to LISTENING"
        )
        if not runtime.state_machine.wake():
            runtime.logger.debug("State machine rejected wake transition")
            return

    try:
        record_audio, transcribe_audio = runtime.load_voice_input()
        runtime.logger.info("Waking up - recording user's question...")
        audio = record_audio()
        if audio is None or len(audio) == 0:
            runtime.logger.warning("No audio recorded after wake-word")
            return

        runtime.logger.info("Transcribing wake-word audio...")
        user_input = transcribe_audio(audio)
        if not user_input:
            runtime.logger.warning("No speech transcribed from wake-word recording")
            return

        runtime.logger.info(f"Wake-word transcription: '{user_input}'")
        if runtime.command_parser:
            try:
                runtime.logger.debug(
                    f"Sending wake-word command to parser: '{user_input}'"
                )
                request = runtime.request_factory(confidence=0.95)
                runtime.command_parser.process_wake_word_event(request)
            except Exception as exc:
                runtime.logger.error(f"Error processing wake-word event: {exc}")
    except Exception as exc:
        runtime.logger.error(f"Error in wake-word callback: {exc}")
