"""Command-line parsing and interactive execution for ``wrapper.argo``."""

from __future__ import annotations

from dataclasses import dataclass
import os
import sys
import uuid
from typing import Any, Sequence


@dataclass(frozen=True)
class CliOptions:
    session_name: str | None = None
    mode: str | None = None
    persona: str = "neutral"
    replay_n: int | None = None
    replay_session: bool = False
    strict_mode: bool = True
    transcribe_file: str | None = None
    voice_enabled: bool | None = None
    message: str = ""


def parse_cli_args(argv: Sequence[str]) -> CliOptions:
    """Parse ARGO's ordered CLI flags without mutating process state."""
    args = list(argv)
    values: dict[str, Any] = {}
    if len(args) >= 2 and args[0] == "--transcribe":
        values["transcribe_file"] = args[1]
        args = args[2:]
    if len(args) >= 2 and args[0] == "--session":
        values["session_name"] = args[1]
        args = args[2:]
    if len(args) >= 2 and args[0] == "--mode":
        values["mode"] = args[1]
        args = args[2:]
    if len(args) >= 2 and args[0] == "--persona":
        values["persona"] = args[1]
        args = args[2:]
    if args and args[0] == "--strict":
        args = args[1:]
        if args and args[0] in ("off", "false", "0"):
            values["strict_mode"] = False
            args = args[1:]
    if len(args) >= 2 and args[0] == "--replay":
        replay = args[1]
        if replay == "session":
            values["replay_session"] = True
        elif replay.startswith("last:"):
            try:
                values["replay_n"] = int(replay.split(":", 1)[1])
            except ValueError as exc:
                raise ValueError("Invalid replay value. Use last:N or session") from exc
        else:
            raise ValueError("Invalid replay value. Use last:N or session")
        args = args[2:]
    if args and args[0] == "--voice":
        values["voice_enabled"] = True
        args = args[1:]
    if args and args[0] == "--no-voice":
        values["voice_enabled"] = False
        args = args[1:]
    values["message"] = " ".join(args)
    return CliOptions(**values)


def _apply_voice_environment(enabled: bool | None) -> None:
    if enabled is None:
        return
    value = "true" if enabled else "false"
    os.environ["VOICE_ENABLED"] = value
    os.environ["PIPER_ENABLED"] = value


def _run_interactive(runtime: Any, options: CliOptions) -> None:
    print("\n📌 Interactive Mode (Voice PTT - Hold SPACEBAR to speak)\n", file=sys.stderr)
    try:
        from voice_input import start_continuous_audio_stream

        if not start_continuous_audio_stream():
            runtime.logger.warning(
                "Failed to start continuous audio stream (wake-word will not work)"
            )
    except Exception as exc:
        runtime.logger.warning(f"Error starting audio stream: {exc}")

    voice_input_available = False
    get_voice_input_ptt = None
    try:
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(runtime.__file__)))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        try:
            import keyboard  # noqa: F401
            from voice_input import get_voice_input_ptt as ptt

            runtime.logger.debug("✓ keyboard module imported successfully")
            runtime.logger.debug("✓ voice_input module imported successfully")
            get_voice_input_ptt = ptt
            voice_input_available = True
        except ImportError as exc:
            runtime.logger.debug(f"✗ keyboard/voice_input import failed: {exc}")
            print(
                f"⚠️  Voice input not available (ImportError: {exc}), falling back to text input",
                file=sys.stderr,
            )
            print("    To enable PTT: pip install keyboard", file=sys.stderr)
    except Exception as exc:
        runtime.logger.debug(f"✗ Unexpected error in voice_input init: {exc}")
        print(f"⚠️  Voice input not available ({exc}), falling back to text input", file=sys.stderr)

    try:
        while True:
            try:
                input_was_from_voice = False
                if voice_input_available and sys.stdin.isatty():
                    print("\n🎤 Hold SPACEBAR to record (or type 'exit' to quit):", file=sys.stderr)
                    runtime.pause_wake_word_detector()
                    try:
                        user_input = get_voice_input_ptt().strip()
                    finally:
                        runtime.resume_wake_word_detector()
                    input_was_from_voice = True
                    if not user_input:
                        continue
                else:
                    user_input = input("argo > ").strip()

                lower = user_input.lower()
                if lower in ("exit", "quit"):
                    print("\nGoodbye.", file=sys.stderr)
                    break
                if not user_input:
                    continue
                if lower.startswith("list conversations"):
                    print(runtime.list_conversations())
                    continue
                if lower.startswith("show yesterday"):
                    print(runtime.show_by_date("yesterday"))
                    continue
                if lower.startswith("show today"):
                    print(runtime.show_by_date("today"))
                    continue
                if lower.startswith("show ") and lower.count("-") == 2:
                    print(runtime.show_by_date(user_input[5:].strip()))
                    continue
                if lower.startswith("show topic "):
                    print(runtime.show_by_topic(user_input[11:].strip()))
                    continue
                if lower.startswith("open "):
                    success, message, context = runtime.get_conversation_context(
                        user_input[5:].strip()
                    )
                    print(message)
                    if success and context:
                        print("(Ready to continue. Type your next question.)", file=sys.stderr)
                    continue
                if lower.startswith("summarize "):
                    print(runtime.summarize_conversation(user_input[10:].strip()))
                    continue

                runtime.run_argo(
                    user_input,
                    active_mode=options.mode,
                    replay_n=options.replay_n,
                    replay_session=options.replay_session,
                    strict_mode=options.strict_mode,
                    persona=options.persona,
                    voice_mode=input_was_from_voice,
                )
                print()
            except KeyboardInterrupt:
                print(
                    "\n[Interrupted. Type your next question or 'exit' to quit]\n",
                    file=sys.stderr,
                )
    except EOFError:
        print("\nSession ended.", file=sys.stderr)


def run_cli(runtime: Any, argv: Sequence[str] | None = None) -> int:
    """Run single-shot, transcription, or interactive CLI against a loaded runtime."""
    try:
        options = parse_cli_args(sys.argv[1:] if argv is None else argv)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _apply_voice_environment(options.voice_enabled)

    message = options.message
    interactive = not message
    if options.transcribe_file:
        confirmed, transcript, _artifact = runtime.transcribe_and_confirm(
            options.transcribe_file
        )
        if not confirmed:
            return 1
        message = transcript
        interactive = False

    runtime.SESSION_ID = (
        runtime.resolve_session_id(options.session_name)
        if options.session_name
        else str(uuid.uuid4())
    )
    if interactive:
        _run_interactive(runtime, options)
    else:
        runtime.run_argo(
            message,
            active_mode=options.mode,
            replay_n=options.replay_n,
            replay_session=options.replay_session,
            strict_mode=options.strict_mode,
            persona=options.persona,
        )
    return 0
