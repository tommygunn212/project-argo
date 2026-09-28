"""Core classified interaction runtime behind ``wrapper.argo``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


@dataclass(frozen=True)
class InteractionRuntime:
    """Explicit dependencies for one legacy wrapper interaction."""

    classify_input: Callable[[str], str]
    classify_verbosity: Callable[[str], str]
    send_output: Callable[[str], None]
    append_daily_log: Callable[..., None]
    build_replay_context: Callable[..., Any]
    compose_prompt: Callable[..., Any]
    generate_response: Callable[[Any], str]
    audit_and_record: Callable[..., None]
    session_id: str
    mode_enforcement: str
    state_machine_available: bool
    state_machine: Any
    wake_word_detector_available: bool
    resume_wake_word_detector: Callable[[], Any]
    logger: Any


def run_classified_interaction(
    runtime: InteractionRuntime,
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
    """Classify, generate, deliver, and record one wrapper interaction."""
    intent = runtime.classify_input(user_input)
    classified_verbosity = runtime.classify_verbosity(user_input)

    if strict_mode and intent in ("empty", "ambiguous", "low_intent"):
        output = "Input is ambiguous. Please clarify what you want to do."
        runtime.send_output(output)
        runtime.append_daily_log(
            timestamp_iso=datetime.now().isoformat(timespec="seconds"),
            session_id=runtime.session_id,
            user_prompt=user_input,
            model_response=output,
            active_mode=active_mode,
            replay_n=replay_n,
            replay_session=replay_session,
            persona=persona,
            verbosity=classified_verbosity,
        )
        print(output)
        return

    if intent == "command":
        output = "Commands not yet implemented. Please provide a question or statement."
        runtime.append_daily_log(
            timestamp_iso=datetime.now().isoformat(timespec="seconds"),
            session_id=runtime.session_id,
            user_prompt=user_input,
            model_response=output,
            active_mode=active_mode,
            replay_n=replay_n,
            replay_session=replay_session,
            persona=persona,
            verbosity=classified_verbosity,
            replay_policy=None,
        )
        print(output)
        return

    replay_context = runtime.build_replay_context(
        session_id=runtime.session_id,
        replay_n=replay_n,
        replay_session=replay_session,
        replay_reason=replay_reason,
        voice_mode=voice_mode,
    )
    prompt = runtime.compose_prompt(
        user_input=user_input,
        active_mode=active_mode,
        persona=persona,
        classified_verbosity=classified_verbosity,
        context_strength=replay_context.context_strength,
        replay_block=replay_context.block,
        voice_mode=voice_mode,
        mode_enforcement=runtime.mode_enforcement,
    )
    output = runtime.generate_response(prompt.full_prompt)
    runtime.send_output(output)

    if runtime.state_machine_available and runtime.state_machine:
        if runtime.state_machine.current_state == "SPEAKING":
            if not runtime.state_machine.stop_audio():
                runtime.logger.warning(
                    "Failed to transition from SPEAKING to LISTENING after audio playback"
                )
        if runtime.wake_word_detector_available:
            runtime.resume_wake_word_detector()

    runtime.audit_and_record(
        user_input=user_input,
        output=output,
        prompt=prompt,
        session_id=runtime.session_id,
        active_mode=active_mode,
        replay_n=replay_n,
        replay_session=replay_session,
        replay_policy=replay_context.policy,
        persona=persona,
    )
