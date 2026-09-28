"""Characterization tests for the classic pipeline transcription boundary."""

from unittest.mock import Mock

import numpy as np

from core.pipeline import ArgoPipeline


class _Manager:
    def __init__(self, result=None, *, model=object(), error=None):
        self.model = model
        self.result = result
        self.error = error
        self.calls = []

    def transcribe(self, audio_data, **kwargs):
        self.calls.append((audio_data.copy(), kwargs))
        if self.error:
            raise self.error
        return self.result


def _pipeline(manager):
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.logger = Mock()
    pipeline.stt_engine_manager = manager
    pipeline.stt_engine = "faster"
    pipeline._stt_initial_prompt = "Argo, Tommy"
    pipeline._last_stt_metrics = None
    pipeline._record_timeline = Mock()
    pipeline.broadcast = Mock()
    pipeline._should_reject_audio = Mock(return_value=(False, ""))
    return pipeline


def test_transcribe_returns_empty_when_engine_is_not_initialized():
    pipeline = _pipeline(_Manager(model=None))

    assert pipeline.transcribe(np.ones(8, dtype=np.float32)) == ""
    pipeline.logger.error.assert_called_once_with("[STT] Engine not initialized")


def test_transcribe_rejected_audio_never_reaches_engine():
    manager = _Manager()
    pipeline = _pipeline(manager)
    pipeline._should_reject_audio.return_value = (True, "too quiet")

    assert pipeline.transcribe(np.zeros(1600, dtype=np.float32), "turn-1") == ""

    assert manager.calls == []
    pipeline._record_timeline.assert_any_call(
        "STT_DISCARD too quiet", stage="stt", interaction_id="turn-1"
    )


def test_transcribe_normalizes_audio_and_records_metrics():
    manager = _Manager(
        {
            "text": "hello",
            "engine": "faster",
            "duration_ms": 25.0,
            "segments": [{"text": "hello"}],
        }
    )
    pipeline = _pipeline(manager)
    audio = np.array([0.0, 2.0, -2.0, 0.5], dtype=np.float32)

    assert pipeline.transcribe(audio, "turn-2") == "hello"

    sent_audio, options = manager.calls[0]
    assert np.max(np.abs(sent_audio)) == 1.0
    assert options == {
        "language": "en",
        "beam_size": 1,
        "condition_on_previous_text": False,
        "initial_prompt": "Argo, Tommy",
    }
    metrics = pipeline._last_stt_metrics
    assert metrics["engine"] == "faster"
    assert metrics["text_len"] == 5
    assert metrics["peak"] == 2.0
    pipeline.broadcast.assert_called_once_with(
        "stt_metrics", {"interaction_id": "turn-2", **metrics}
    )


def test_transcribe_contains_engine_failure_and_records_error():
    pipeline = _pipeline(_Manager(error=RuntimeError("broken STT")))

    assert pipeline.transcribe(np.ones(1600, dtype=np.float32), "turn-3") == ""

    pipeline._record_timeline.assert_any_call(
        "STT_ERROR", stage="stt", interaction_id="turn-3"
    )
    pipeline.logger.error.assert_called_with(
        "[STT] Failed: broken STT", exc_info=True
    )
