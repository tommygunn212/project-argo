from types import SimpleNamespace
from unittest.mock import Mock

from core.backend_control import BackendControlRuntime, dispatch_backend_control


def _runtime(*, voice_mode="classic", pipeline=None, audio=None, main_thread=None):
    state = {"voice_mode": voice_mode}
    runtime = BackendControlRuntime(
        smooth_voice_mode="smooth",
        classic_voice_mode="classic",
        get_voice_mode=lambda: state["voice_mode"],
        set_voice_mode=Mock(side_effect=lambda mode, _reason: state.update(voice_mode=mode)),
        set_listening_enabled=Mock(),
        set_server_enabled=Mock(),
        get_pipeline=lambda: pipeline,
        get_audio=lambda: audio,
        get_main_loop_thread=lambda: main_thread,
        start_main_loop_thread=Mock(return_value=True),
        interrupt_current_response=Mock(),
        hard_reset_pipeline=Mock(return_value={"actions": ["released"]}),
        run_noise_calibration=Mock(),
        clear_overrides=Mock(),
        next_interaction_overrides={"suppress_tts": True},
        broadcast=Mock(),
        event_logger=Mock(),
        logger=Mock(),
    )
    return runtime


def test_smooth_voice_refuses_plain_resume_without_starting_classic():
    runtime = _runtime(voice_mode="smooth")

    dispatch_backend_control(runtime, "RESUME")

    runtime.set_listening_enabled.assert_not_called()
    runtime.start_main_loop_thread.assert_not_called()
    runtime.event_logger.assert_any_call("UI_CMD_START_VAD_REFUSED", stage="ui")


def test_explicit_classic_switch_is_the_only_resume_that_reclaims_mic():
    pipeline = SimpleNamespace(current_state="IDLE", transition_state=Mock())
    runtime = _runtime(voice_mode="smooth", pipeline=pipeline)

    dispatch_backend_control(runtime, "USE_CLASSIC_VOICE")

    runtime.set_voice_mode.assert_called_once_with(
        "classic", "user switched to classic voice"
    )
    runtime.set_listening_enabled.assert_called_once_with(True)
    runtime.start_main_loop_thread.assert_called_once_with()
    pipeline.transition_state.assert_called_once_with("LISTENING", source="ui")


def test_server_stop_interrupts_and_breaks_wedged_turn():
    audio = SimpleNamespace(stop=Mock())
    runtime = _runtime(audio=audio)

    dispatch_backend_control(runtime, "SERVER_STOP")

    runtime.set_server_enabled.assert_called_once_with(False)
    runtime.set_listening_enabled.assert_called_once_with(False)
    runtime.interrupt_current_response.assert_called_once_with(
        "SERVER_STOP", target_state="IDLE"
    )
    runtime.hard_reset_pipeline.assert_called_once_with("SERVER_STOP")
    audio.stop.assert_called_once_with()
