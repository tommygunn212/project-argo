"""Characterization tests for the coordinator's lazy Silero VAD gate."""

from __future__ import annotations

from unittest.mock import Mock

from core.coordinator import Coordinator


def _coordinator() -> Coordinator:
    coordinator = Coordinator.__new__(Coordinator)
    coordinator.logger = Mock()
    return coordinator


def test_speech_gate_is_created_once_and_cached(monkeypatch):
    gate = Mock(available=True)
    constructor = Mock(return_value=gate)
    monkeypatch.setattr("core.vad_silero.SileroGate", constructor)
    coordinator = _coordinator()

    assert coordinator._speech_gate() is gate
    assert coordinator._speech_gate() is gate

    constructor.assert_called_once_with(
        sample_rate=coordinator.AUDIO_SAMPLE_RATE,
        threshold=coordinator.VAD_SPEECH_PROBABILITY,
    )


def test_unavailable_speech_gate_is_not_retried(monkeypatch):
    constructor = Mock(return_value=Mock(available=False))
    monkeypatch.setattr("core.vad_silero.SileroGate", constructor)
    coordinator = _coordinator()

    assert coordinator._speech_gate() is None
    assert coordinator._speech_gate() is None

    constructor.assert_called_once_with(
        sample_rate=coordinator.AUDIO_SAMPLE_RATE,
        threshold=coordinator.VAD_SPEECH_PROBABILITY,
    )
    assert coordinator._silero_gate_failed is True


def test_speech_gate_constructor_failure_is_cached(monkeypatch):
    constructor = Mock(side_effect=RuntimeError("model unavailable"))
    monkeypatch.setattr("core.vad_silero.SileroGate", constructor)
    coordinator = _coordinator()

    assert coordinator._speech_gate() is None
    assert coordinator._speech_gate() is None

    constructor.assert_called_once()
    coordinator.logger.exception.assert_called_once()
    assert coordinator._silero_gate_failed is True

