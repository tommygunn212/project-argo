"""Characterization tests for the classic backend composition loop."""

from types import SimpleNamespace
from unittest.mock import Mock

import main


def _install_common(monkeypatch):
    audio = Mock()
    pipeline = Mock()
    audio_factory = Mock(return_value=audio)
    pipeline_factory = Mock(return_value=pipeline)
    monkeypatch.setattr(main.time, "sleep", Mock())
    monkeypatch.setattr(main, "AudioManager", audio_factory)
    monkeypatch.setattr(main, "ArgoPipeline", pipeline_factory)
    monkeypatch.setattr(main, "_init_recovery_system", Mock())
    monkeypatch.setattr(main, "broadcast_msg", Mock())
    monkeypatch.setattr(main, "run_classic_capture_loop", Mock())
    monkeypatch.setattr(main, "LISTENING_ENABLED", True)
    monkeypatch.setattr(main, "SERVER_ENABLED", True)
    monkeypatch.setattr(main, "config", {
        "audio.vad_threshold": 0.25,
        "audio.calibration_max_multiple": 3.0,
        "audio.barge_in_threshold": 0.5,
    })
    return audio, pipeline, audio_factory, pipeline_factory


def test_main_loop_startup_failure_publishes_error_without_capture(monkeypatch):
    audio, pipeline, _audio_factory, _pipeline_factory = _install_common(monkeypatch)
    monkeypatch.setattr(
        main,
        "start_classic_runtime",
        Mock(side_effect=RuntimeError("startup failed")),
    )

    main.main_loop()

    assert main.audio_ref is audio
    assert main.pipeline_ref is pipeline
    main.broadcast_msg.assert_called_once_with("status", "ERROR")
    main.run_classic_capture_loop.assert_not_called()


def test_main_loop_calibrates_and_dispatches_capture(monkeypatch):
    audio, pipeline, audio_factory, pipeline_factory = _install_common(monkeypatch)
    monkeypatch.setattr(main, "start_classic_runtime", Mock(return_value=True))
    calibrate = Mock(
        return_value=SimpleNamespace(vad_threshold=0.4, barge_in_threshold=0.7)
    )
    monkeypatch.setattr(main, "calibrate_ambient_noise", calibrate)

    main.main_loop()

    audio_factory.assert_called_once_with(
        input_device_index=main.AUDIO_INPUT_INDEX,
        output_device_index=main.AUDIO_OUTPUT_INDEX,
        on_owner_change=audio_factory.call_args.kwargs["on_owner_change"],
    )
    pipeline_factory.assert_called_once_with(audio, main.broadcast_msg)
    pipeline.transition_state.assert_called_once_with("LISTENING")
    assert callable(main._noise_calibrate_fn)
    options = main.run_classic_capture_loop.call_args.kwargs
    assert options["audio"] is audio
    assert options["pipeline"] is pipeline
    assert options["vad_threshold"] == 0.4
    assert options["barge_in_threshold"] == 0.7
    assert options["get_server_enabled"]() is True
    assert options["get_listening_enabled"]() is True
