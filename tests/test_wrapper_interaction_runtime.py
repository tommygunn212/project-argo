from types import SimpleNamespace
from unittest.mock import Mock

from wrapper.interaction_runtime import InteractionRuntime, run_classified_interaction


def _runtime(*, intent="question", state_machine=None):
    replay = SimpleNamespace(block="history", policy={"mode": "recent"}, context_strength=2)
    prompt = SimpleNamespace(full_prompt=b"composed")
    return InteractionRuntime(
        classify_input=Mock(return_value=intent),
        classify_verbosity=Mock(return_value="short"),
        send_output=Mock(),
        append_daily_log=Mock(),
        build_replay_context=Mock(return_value=replay),
        compose_prompt=Mock(return_value=prompt),
        generate_response=Mock(return_value="answer"),
        audit_and_record=Mock(),
        session_id="session-1",
        mode_enforcement="mode rules",
        state_machine_available=state_machine is not None,
        state_machine=state_machine,
        wake_word_detector_available=state_machine is not None,
        resume_wake_word_detector=Mock(),
        logger=Mock(),
    )


def test_ambiguous_input_is_logged_without_generation(capsys):
    runtime = _runtime(intent="ambiguous")

    run_classified_interaction(runtime, "maybe", strict_mode=True)

    runtime.send_output.assert_called_once_with(
        "Input is ambiguous. Please clarify what you want to do."
    )
    runtime.append_daily_log.assert_called_once()
    runtime.generate_response.assert_not_called()
    assert "Input is ambiguous" in capsys.readouterr().out


def test_generated_response_resets_speaking_state_and_is_audited():
    state_machine = SimpleNamespace(current_state="SPEAKING", stop_audio=Mock(return_value=True))
    runtime = _runtime(state_machine=state_machine)

    run_classified_interaction(runtime, "explain this", voice_mode=True)

    runtime.generate_response.assert_called_once_with(b"composed")
    runtime.send_output.assert_called_once_with("answer")
    state_machine.stop_audio.assert_called_once_with()
    runtime.resume_wake_word_detector.assert_called_once_with()
    runtime.audit_and_record.assert_called_once()
    assert runtime.audit_and_record.call_args.kwargs["replay_policy"] == {
        "mode": "recent"
    }


def test_placeholder_command_path_does_not_generate_or_speak(capsys):
    runtime = _runtime(intent="command")

    run_classified_interaction(runtime, "do it")

    runtime.generate_response.assert_not_called()
    runtime.send_output.assert_not_called()
    runtime.append_daily_log.assert_called_once()
    assert "Commands not yet implemented" in capsys.readouterr().out
