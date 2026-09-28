"""Ownership and polling tests for coordinator music interruption."""

from unittest.mock import Mock

from core.coordinator import Coordinator


class SequencedPlayer:
    def __init__(self, states):
        self.states = iter(states)
        self.stop = Mock()

    @property
    def is_playing(self):
        return next(self.states)


def _coordinator(interrupt_check):
    coordinator = Coordinator.__new__(Coordinator)
    coordinator.logger = Mock()
    coordinator.trigger = Mock()
    coordinator.trigger._check_for_interrupt.side_effect = interrupt_check
    coordinator.release_audio = Mock()
    return coordinator


def test_music_interrupt_stops_player_and_releases_audio(monkeypatch):
    coordinator = _coordinator([True])
    player = SequencedPlayer([True])
    sleep = Mock()
    monkeypatch.setattr("core.coordinator.time.sleep", sleep)

    coordinator._monitor_music_interrupt(player)

    player.stop.assert_called_once_with()
    sleep.assert_not_called()
    coordinator.release_audio.assert_called_once_with("MUSIC")


def test_music_monitor_polls_until_playback_ends(monkeypatch):
    coordinator = _coordinator([False])
    player = SequencedPlayer([True, False])
    sleep = Mock()
    monkeypatch.setattr("core.coordinator.time.sleep", sleep)

    coordinator._monitor_music_interrupt(player)

    player.stop.assert_not_called()
    sleep.assert_called_once_with(0.2)
    coordinator.release_audio.assert_called_once_with("MUSIC")


def test_interrupt_probe_error_is_contained_and_polling_continues(monkeypatch):
    coordinator = _coordinator([RuntimeError("probe failed")])
    player = SequencedPlayer([True, False])
    sleep = Mock()
    monkeypatch.setattr("core.coordinator.time.sleep", sleep)

    coordinator._monitor_music_interrupt(player)

    sleep.assert_called_once_with(0.2)
    coordinator.release_audio.assert_called_once_with("MUSIC")
    assert any(
        "probe failed" in call.args[0]
        for call in coordinator.logger.debug.call_args_list
    )


def test_outer_monitor_failure_still_releases_music_audio(monkeypatch):
    coordinator = _coordinator([])
    player = Mock()
    type(player).is_playing = property(
        lambda _self: (_ for _ in ()).throw(RuntimeError("player failed"))
    )
    monkeypatch.setattr("core.coordinator.time.sleep", Mock())

    coordinator._monitor_music_interrupt(player)

    coordinator.release_audio.assert_called_once_with("MUSIC")
    assert any(
        "player failed" in call.args[0]
        for call in coordinator.logger.error.call_args_list
    )
