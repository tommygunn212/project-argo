"""Saying "Playing" is a claim about sound, not about launching a process.

Tommy: "I try playing music Argo said it was playing I could not hear it."

Reproduced: music_play returned {"playing": true, "message": "Playing."} and
music_status said playing: false three seconds later. The stream 404s because
those tracks are no longer in Jellyfin, ffplay exits instantly with code 0,
its stderr goes to DEVNULL, and the playing flag was set before anything was
confirmed alive.
"""

import pytest

from core import realtime_tools as T


class Player:
    """A player that starts something and then reports whether it survived."""

    def __init__(self, survives: bool, track=None):
        self._survives = survives
        self.current_track = track if track is not None else {
            "artist": "the clash", "song": "Che Guevara",
        }

    def play_by_keyword(self, _query):
        return True          # "I launched something"

    play_by_song = play_by_artist = play_by_genre = play_by_keyword

    def play_random(self):
        return True

    def play(self, *a, **k):
        return True

    def is_playing(self):
        return self._survives


@pytest.fixture(autouse=True)
def instant_settle(monkeypatch):
    """Don't make the suite wait out the real settle delay."""
    monkeypatch.setattr(T, "PLAYBACK_SETTLE_SECONDS", 0.01)


def _use(monkeypatch, player):
    monkeypatch.setattr("core.music_player.get_music_player", lambda: player)


# --- the regression -------------------------------------------------------

def test_playback_that_dies_immediately_is_reported_as_failure(monkeypatch):
    """The exact bug: launched, died, ARGO said 'Playing.'"""
    _use(monkeypatch, Player(survives=False))

    d = T.music_play("play some music")

    assert d["ok"] is False
    assert d["playing"] is False
    assert d["error"] == "playback_died"
    assert "no sound" in d["message"]


def test_the_message_names_the_track_so_he_knows_what_failed(monkeypatch):
    _use(monkeypatch, Player(survives=False))
    d = T.music_play("play the clash")
    assert "the clash" in d["message"] and "Che Guevara" in d["message"]


def test_real_playback_is_reported_as_playing(monkeypatch):
    _use(monkeypatch, Player(survives=True))

    d = T.music_play("play the clash")

    assert d["ok"] is True and d["playing"] is True
    assert d["message"].startswith("Playing the clash - Che Guevara")


def test_ok_is_never_true_while_playing_is_false(monkeypatch):
    """These two disagreeing is what produced the false announcement."""
    for survives in (True, False):
        _use(monkeypatch, Player(survives=survives))
        d = T.music_play("anything")
        assert d["ok"] == d["playing"]


# --- nothing matched is different from playback dying ---------------------

def test_no_match_is_reported_as_no_match(monkeypatch):
    class NoMatch(Player):
        def play_by_keyword(self, _query):
            return False
        play_by_song = play_by_artist = play_by_genre = play_by_keyword

    _use(monkeypatch, NoMatch(survives=False))
    d = T.music_play("play something that does not exist")
    assert d["error"] == "no_match"


# --- the era path had the same lie ---------------------------------------

def test_era_playback_is_verified_too(monkeypatch):
    player = Player(survives=False)
    _use(monkeypatch, player)
    monkeypatch.setattr(
        "core.music_player.MusicDatabase",
        lambda *a, **k: type("DB", (), {
            "query_tracks": lambda self, **kw: [
                {"song": "London Calling", "artist": "the clash",
                 "path": "jellyfin://abc", "year": 1979}
            ]
        })(),
    )

    d = T.music_play_era("the 70s")

    assert d["ok"] is False and d["playing"] is False
    assert d["error"] == "playback_died"
    assert d["now_playing"]["title"] == "London Calling"


def test_a_broken_player_does_not_raise(monkeypatch):
    class Exploding(Player):
        def is_playing(self):
            raise RuntimeError("audio device vanished")

    _use(monkeypatch, Exploding(survives=False))
    d = T.music_play("anything")
    assert d["ok"] is False and d["playing"] is False
