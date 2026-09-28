"""Public wrapper interaction preflight and composition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Callable


@dataclass(frozen=True)
class PublicRuntime:
    """Explicit dependencies used before classified wrapper execution."""

    update_preferences: Callable[[str], dict]
    dispatch_music_volume: Callable[..., bool]
    dispatch_self_knowledge: Callable[..., bool]
    neural_terminology_sink: Callable[[Callable[[str], None]], Callable[[str], None]]
    dispatch_governance: Callable[..., bool]
    prepare_conversation: Callable[..., Any]
    run_internal: Callable[..., None]
    get_output_sink: Callable[[], Any] | None
    get_send_output: Callable[[], Callable[[str], None]]
    set_send_output: Callable[[Callable[[str], None]], None]
    repository_root: Path
    command_parser_available: bool
    command_parser: Any
    command_type: Any
    output_sink_available: bool
    state_machine_available: bool
    state_machine: Any
    transition_to_thinking: Callable[[], bool]
    transition_to_speaking: Callable[[], bool]


def run_public_interaction(
    runtime: PublicRuntime,
    user_input: str,
    *,
    active_mode: str | None = None,
    replay_n: int | None = None,
    replay_session: bool = False,
    strict_mode: bool = True,
    persona: str = "neutral",
    verbosity: str = "short",
    replay_reason: str = "continuation",
    voice_mode: bool = False,
) -> None:
    """Apply public preflight gates, then enter classified execution."""
    if voice_mode:
        replay_n = None
        replay_session = False

    preferences = runtime.update_preferences(user_input)
    send_output = runtime.get_send_output()
    if runtime.dispatch_music_volume(user_input, send_output):
        return
    if runtime.dispatch_self_knowledge(
        user_input, send_output, runtime.repository_root
    ):
        return

    send_output = runtime.neural_terminology_sink(send_output)
    runtime.set_send_output(send_output)
    if runtime.dispatch_governance(user_input, send_output):
        return

    if runtime.command_parser_available and runtime.command_parser:
        parsed = runtime.command_parser.parse(user_input)
        if parsed.command_type == runtime.command_type.STOP:
            if runtime.output_sink_available and runtime.get_output_sink:
                try:
                    runtime.get_output_sink().stop()
                    print(
                        "[AUDIO] Stopped playback (hard stop, <50ms latency)",
                        file=sys.stderr,
                    )
                except Exception as error:
                    print(f"⚠ OutputSink.stop() error: {error}", file=sys.stderr)
            if runtime.state_machine_available and runtime.state_machine:
                if runtime.state_machine.stop_audio():
                    print(
                        "[STATE] Stopped audio (SPEAKING -> LISTENING)",
                        file=sys.stderr,
                    )
            return
        if parsed.command_type == runtime.command_type.SLEEP:
            if runtime.state_machine_available and runtime.state_machine:
                if runtime.state_machine.sleep():
                    print("[STATE] Going to sleep (-> SLEEP)", file=sys.stderr)
            return
        if parsed.command_type == runtime.command_type.WAKE:
            if runtime.state_machine_available and runtime.state_machine:
                if runtime.state_machine.wake():
                    print("[STATE] Woke up (SLEEP -> LISTENING)", file=sys.stderr)
            return
        if parsed.command_type in (
            runtime.command_type.ACTION,
            runtime.command_type.QUESTION,
        ):
            user_input = parsed.cleaned_text

    if (
        runtime.state_machine_available
        and runtime.state_machine
        and runtime.state_machine.is_listening
    ):
        runtime.transition_to_thinking()

    preparation = runtime.prepare_conversation(
        user_input, prefs=preferences, voice_mode=voice_mode
    )
    if preparation.is_recall:
        print(preparation.recall_output)
        send_output(preparation.recall_output)
        return

    runtime.transition_to_speaking()
    runtime.run_internal(
        preparation.composed_input,
        active_mode=active_mode,
        replay_n=replay_n,
        replay_session=replay_session,
        strict_mode=strict_mode,
        persona=persona,
        verbosity=verbosity,
        replay_reason=replay_reason,
        voice_mode=voice_mode,
    )
