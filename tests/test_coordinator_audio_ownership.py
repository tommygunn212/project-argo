"""Characterization tests for coordinator audio ownership."""

import threading
from unittest.mock import Mock

import pytest

from core.coordinator import Coordinator


def _coordinator(owner=None):
    coordinator = Coordinator.__new__(Coordinator)
    coordinator._audio_owner_lock = threading.Lock()
    coordinator.audio_owner = Mock()
    coordinator.audio_owner.get_owner.return_value = owner
    return coordinator


def test_acquire_audio_claims_free_owner_and_logs(monkeypatch):
    coordinator = _coordinator()
    event = Mock()
    monkeypatch.setattr("core.coordinator.log_event", event)

    coordinator.acquire_audio("TTS")

    coordinator.audio_owner.acquire.assert_called_once_with("TTS")
    event.assert_called_once_with("AUDIO_ACQUIRED owner=TTS")


def test_acquire_audio_rejects_competing_owner_before_mutation(monkeypatch):
    coordinator = _coordinator("MUSIC")
    event = Mock()
    monkeypatch.setattr("core.coordinator.log_event", event)

    with pytest.raises(RuntimeError, match="Audio already owned"):
        coordinator.acquire_audio("TTS")

    coordinator.audio_owner.acquire.assert_not_called()
    event.assert_called_once_with("AUDIO_CONTESTED owner=MUSIC requested=TTS")


def test_release_audio_only_releases_matching_owner(monkeypatch):
    coordinator = _coordinator("TTS")
    event = Mock()
    monkeypatch.setattr("core.coordinator.log_event", event)

    coordinator.release_audio("TTS")

    coordinator.audio_owner.release.assert_called_once_with("TTS")
    event.assert_called_once_with("AUDIO_RELEASED owner=TTS")

    coordinator.audio_owner.reset_mock()
    event.reset_mock()
    coordinator.audio_owner.get_owner.return_value = "MUSIC"
    coordinator.release_audio("TTS")
    coordinator.audio_owner.release.assert_not_called()
    event.assert_not_called()


def test_force_release_audio_reports_prior_owner(monkeypatch):
    coordinator = _coordinator("MUSIC")
    event = Mock()
    monkeypatch.setattr("core.coordinator.log_event", event)

    coordinator.force_release_audio("BARGE_IN")

    coordinator.audio_owner.force_release.assert_called_once_with("BARGE_IN")
    event.assert_called_once_with(
        "AUDIO_FORCED_RELEASE prior=MUSIC reason=BARGE_IN"
    )

