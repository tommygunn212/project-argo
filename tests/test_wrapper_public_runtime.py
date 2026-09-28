from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from wrapper.public_runtime import PublicRuntime, run_public_interaction


class CommandType(Enum):
    STOP = "stop"
    SLEEP = "sleep"
    WAKE = "wake"
    ACTION = "action"
    QUESTION = "question"


def _runtime(*, parsed=None, music_handled=False, state_machine=None):
    original_sink = Mock()
    wrapped_sink = Mock()
    parser = Mock()
    parser.parse.return_value = parsed or SimpleNamespace(
        command_type=CommandType.QUESTION,
        cleaned_text="cleaned input",
    )
    preparation = SimpleNamespace(
        is_recall=False,
        recall_output=None,
        composed_input="composed input",
    )
    runtime = PublicRuntime(
        update_preferences=Mock(return_value={"tone": "plain"}),
        dispatch_music_volume=Mock(return_value=music_handled),
        dispatch_self_knowledge=Mock(return_value=False),
        neural_terminology_sink=Mock(return_value=wrapped_sink),
        dispatch_governance=Mock(return_value=False),
        prepare_conversation=Mock(return_value=preparation),
        run_internal=Mock(),
        get_output_sink=Mock(return_value=SimpleNamespace(stop=Mock())),
        get_send_output=Mock(return_value=original_sink),
        set_send_output=Mock(),
        repository_root=Path("repo"),
        command_parser_available=True,
        command_parser=parser,
        command_type=CommandType,
        output_sink_available=True,
        state_machine_available=state_machine is not None,
        state_machine=state_machine,
        transition_to_thinking=Mock(),
        transition_to_speaking=Mock(),
    )
    return runtime


def test_music_preflight_short_circuits_before_sink_wrapping():
    runtime = _runtime(music_handled=True)

    run_public_interaction(runtime, "set volume to 40")

    runtime.neural_terminology_sink.assert_not_called()
    runtime.command_parser.parse.assert_not_called()
    runtime.prepare_conversation.assert_not_called()
    runtime.run_internal.assert_not_called()


def test_voice_mode_forces_stateless_replay_arguments():
    runtime = _runtime()

    run_public_interaction(
        runtime,
        "question",
        replay_n=8,
        replay_session=True,
        voice_mode=True,
    )

    runtime.prepare_conversation.assert_called_once_with(
        "cleaned input", prefs={"tone": "plain"}, voice_mode=True
    )
    assert runtime.run_internal.call_args.kwargs["replay_n"] is None
    assert runtime.run_internal.call_args.kwargs["replay_session"] is False
    assert runtime.run_internal.call_args.kwargs["voice_mode"] is True


def test_stop_command_never_reaches_memory_or_generation():
    parsed = SimpleNamespace(command_type=CommandType.STOP, cleaned_text="stop")
    state_machine = SimpleNamespace(stop_audio=Mock(return_value=True))
    runtime = _runtime(parsed=parsed, state_machine=state_machine)

    run_public_interaction(runtime, "stop")

    runtime.get_output_sink.return_value.stop.assert_called_once_with()
    state_machine.stop_audio.assert_called_once_with()
    runtime.prepare_conversation.assert_not_called()
    runtime.run_internal.assert_not_called()
