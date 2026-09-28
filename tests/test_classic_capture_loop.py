from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from core.classic_capture_loop import run_classic_capture_loop


def _one_iteration():
    calls = iter((True, False))
    return lambda: next(calls)


def _run(*, pipeline, audio, voice_mode="smooth", disable_listening=Mock()):
    run_classic_capture_loop(
        audio=audio,
        pipeline=pipeline,
        get_server_enabled=_one_iteration(),
        get_listening_enabled=lambda: True,
        disable_listening=disable_listening,
        get_voice_mode=lambda: voice_mode,
        smooth_voice_mode="smooth",
        runtime_overrides={},
        input_sample_rate=16_000,
        block_size=512,
        vad_threshold=0.1,
        barge_in_threshold=6.0,
        broadcast=Mock(),
        interrupt_current_response=Mock(),
        next_interaction_overrides={},
        sound_cues=Mock(),
        logger=Mock(),
        event_logger=Mock(),
    )


def test_smooth_voice_never_starts_classic_capture():
    pipeline = SimpleNamespace(
        illegal_transition=False,
        tts_finished_at=0.0,
        is_speaking=False,
        current_state="LISTENING",
        transition_state=Mock(),
        is_barge_in_suppressed=lambda: False,
    )
    audio = Mock()
    audio.read_frame.return_value = np.ones(512, dtype=np.float32)
    audio.get_audio_owner.return_value = "STT"

    _run(pipeline=pipeline, audio=audio, voice_mode="smooth")

    pipeline.transition_state.assert_not_called()
    audio.get_preroll.assert_not_called()


def test_illegal_transition_disables_listening_before_mic_read(monkeypatch):
    monkeypatch.setattr("core.classic_capture_loop.time.sleep", lambda _: None)
    disable_listening = Mock()
    pipeline = SimpleNamespace(illegal_transition=True)
    audio = Mock()

    _run(
        pipeline=pipeline,
        audio=audio,
        voice_mode="classic",
        disable_listening=disable_listening,
    )

    disable_listening.assert_called_once_with()
    audio.read_frame.assert_not_called()
