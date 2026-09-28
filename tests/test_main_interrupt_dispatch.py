"""Contract tests for the dashboard's shared response-interrupt path."""

from types import SimpleNamespace
from unittest.mock import Mock

import main


def _configure(monkeypatch, *, pipeline=None, audio=None):
    cues = SimpleNamespace(stop_active_cue=Mock())
    logger = Mock()
    monkeypatch.setattr(main, "pipeline_ref", pipeline)
    monkeypatch.setattr(main, "audio_ref", audio)
    monkeypatch.setattr(main, "sound_cues", cues)
    monkeypatch.setattr(main, "logger", logger)
    return cues, logger


def test_modern_pipeline_interrupt_is_authoritative(monkeypatch):
    pipeline = SimpleNamespace(
        current_interaction_id="turn-7",
        interrupt_current_response=Mock(),
        stop_signal=Mock(),
        stop_tts=Mock(),
    )
    audio = SimpleNamespace(
        force_release_audio=Mock(), stop_playback=Mock(), clear_buffers=Mock()
    )
    cues, _ = _configure(monkeypatch, pipeline=pipeline, audio=audio)

    main._interrupt_current_response(
        "user_stop", target_state="IDLE", clear_buffers=False
    )

    cues.stop_active_cue.assert_called_once_with(
        "user_stop", interaction_id="turn-7"
    )
    pipeline.interrupt_current_response.assert_called_once_with(
        reason="user_stop",
        interaction_id="turn-7",
        target_state="IDLE",
        clear_buffers=False,
    )
    pipeline.stop_tts.assert_not_called()
    audio.force_release_audio.assert_not_called()


def test_failed_modern_interrupt_falls_back_to_pipeline_and_audio_cleanup(monkeypatch):
    stop_signal = SimpleNamespace(set=Mock())
    pipeline = SimpleNamespace(
        current_interaction_id="turn-8",
        interrupt_current_response=Mock(side_effect=RuntimeError("wedged")),
        stop_signal=stop_signal,
        stop_tts=Mock(),
        is_speaking=True,
    )
    audio = SimpleNamespace(
        force_release_audio=Mock(), stop_playback=Mock(), clear_buffers=Mock()
    )
    _, logger = _configure(monkeypatch, pipeline=pipeline, audio=audio)

    main._interrupt_current_response("restart")

    stop_signal.set.assert_called_once_with()
    pipeline.stop_tts.assert_called_once_with()
    assert pipeline.is_speaking is False
    audio.force_release_audio.assert_called_once_with(
        "restart", interaction_id="turn-8"
    )
    audio.stop_playback.assert_called_once_with()
    audio.clear_buffers.assert_called_once_with()
    assert any("wedged" in call.args[0] for call in logger.warning.call_args_list)


def test_audio_only_interrupt_uses_empty_interaction_and_can_preserve_buffers(
    monkeypatch,
):
    audio = SimpleNamespace(
        force_release_audio=Mock(), stop_playback=Mock(), clear_buffers=Mock()
    )
    cues, _ = _configure(monkeypatch, pipeline=None, audio=audio)

    main._interrupt_current_response("reset", clear_buffers=False)

    cues.stop_active_cue.assert_called_once_with("reset", interaction_id="")
    audio.force_release_audio.assert_called_once_with("reset", interaction_id="")
    audio.stop_playback.assert_called_once_with()
    audio.clear_buffers.assert_not_called()


def test_cleanup_failures_are_contained(monkeypatch):
    pipeline = SimpleNamespace(
        current_interaction_id="turn-9",
        stop_signal=SimpleNamespace(set=Mock(side_effect=RuntimeError("stop failed"))),
        stop_tts=Mock(),
        is_speaking=True,
    )
    audio = SimpleNamespace(
        force_release_audio=Mock(side_effect=RuntimeError("release failed")),
        stop_playback=Mock(),
        clear_buffers=Mock(),
    )
    cues, _ = _configure(monkeypatch, pipeline=pipeline, audio=audio)
    cues.stop_active_cue.side_effect = RuntimeError("cue failed")

    main._interrupt_current_response("shutdown")

    audio.force_release_audio.assert_called_once_with(
        "shutdown", interaction_id="turn-9"
    )
