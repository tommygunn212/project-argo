"""Movies and TV.

Tommy: "it also could not launch a movie". Nothing was broken - ARGO had no
movie capability at all. Every media tool it owned pointed at the music
index, while 238 movies and 580 episodes sat on the Jellyfin server.

Jellyfin is used for SEARCH only; playback is a local player on the local
file, so a media-server problem cannot silence a film on the same disk.
"""

import subprocess
from pathlib import Path

import pytest

from core import realtime_tools as T
from core import video_library as V


@pytest.fixture(autouse=True)
def no_settle(monkeypatch):
    monkeypatch.setattr(V, "PLAYBACK_SETTLE_SECONDS", 0.01)
    yield
    V.stop()


def fake_items(items):
    def _jellyfin(path, params):
        if params.get("IncludeItemTypes") == "Series":
            return {"Items": [{"Id": "series-1", "Name": "True Detective"}]}
        return {"Items": items}
    return _jellyfin


# --- search ---------------------------------------------------------------

def test_search_reports_whether_the_file_is_actually_on_disk(monkeypatch, tmp_path):
    real = tmp_path / "film.mkv"
    real.write_bytes(b"x")
    monkeypatch.setattr(V, "_jellyfin", fake_items([
        {"Id": "1", "Name": "Here", "Type": "Movie", "Path": str(real)},
        {"Id": "2", "Name": "Gone", "Type": "Movie", "Path": str(tmp_path / "missing.mkv")},
    ]))

    results = V.search("anything")

    assert [r["on_disk"] for r in results] == [True, False]


def test_an_episode_search_falls_back_to_the_series(monkeypatch):
    """"Play True Detective" matches no EPISODE title, because episode titles
    do not contain the show's name."""
    calls = []

    def _jellyfin(path, params):
        calls.append(params)
        if params.get("IncludeItemTypes") == "Episode" and params.get("SearchTerm"):
            return {"Items": []}                      # nothing by episode title
        if params.get("IncludeItemTypes") == "Series":
            return {"Items": [{"Id": "s1", "Name": "True Detective"}]}
        return {"Items": [{"Id": "e1", "Name": "Part 1", "Type": "Episode",
                           "SeriesName": "True Detective", "Path": ""}]}

    monkeypatch.setattr(V, "_jellyfin", _jellyfin)

    results = V.search("true detective", kind="episode")

    assert results and results[0]["series"] == "True Detective"
    assert any(p.get("ParentId") == "s1" for p in calls), "should ask for the series' episodes"


def test_a_dead_server_returns_nothing_rather_than_raising(monkeypatch):
    monkeypatch.setattr(V, "_jellyfin", lambda *a, **k: None)
    assert V.search("anything") == []
    assert V.catalogue_size() == {}


# --- playing --------------------------------------------------------------

def test_a_missing_file_is_refused_before_launching_anything(tmp_path):
    d = V.play(str(tmp_path / "not-here.mkv"), "Ghost Film")
    assert d["ok"] is False and d["error"] == "missing_file"
    assert "not on disk" in d["message"]


def test_no_player_installed_says_so(monkeypatch, tmp_path):
    f = tmp_path / "film.mkv"
    f.write_bytes(b"x")
    monkeypatch.setattr(V, "_find_player", lambda: None)

    d = V.play(str(f), "Film")

    assert d["ok"] is False and d["error"] == "no_player"


def test_a_player_that_exits_immediately_is_reported_as_failure(monkeypatch, tmp_path):
    """The music bug in video form: launched is not playing."""
    f = tmp_path / "film.mkv"
    f.write_bytes(b"x")
    # A "player" that exits at once, like a codec failure would.
    monkeypatch.setattr(V, "_find_player", lambda: ("cmd", ["/c", "exit"]))

    d = V.play(str(f), "Broken Film", settle=0.6)

    assert d["ok"] is False and d["error"] == "playback_died"
    assert "nothing is on screen" in d["message"]
    assert V.is_playing() is False


def test_a_player_that_keeps_running_is_reported_as_playing(monkeypatch, tmp_path):
    f = tmp_path / "film.mkv"
    f.write_bytes(b"x")
    monkeypatch.setattr(V, "_find_player", lambda: ("cmd", ["/c", "ping -n 20 127.0.0.1 >nul &&"]))

    d = V.play(str(f), "Long Film", settle=0.6)

    assert d["ok"] is True and d["playing"] is True
    assert V.is_playing() is True
    assert V.now_playing()["title"] == "Long Film"
    assert V.stop() is True
    assert V.is_playing() is False


def test_stopping_when_nothing_plays_is_harmless():
    assert V.stop() is False


# --- the tool surface -----------------------------------------------------

def test_asking_for_nothing_is_refused():
    assert T.video_play("")["error"] == "no_title"


def test_a_title_that_is_not_in_the_library_says_so(monkeypatch):
    monkeypatch.setattr(V, "_jellyfin", lambda *a, **k: {"Items": []})
    d = T.video_play("a film that does not exist")
    assert d["ok"] is False and d["error"] == "not_found"


def test_indexed_but_missing_from_disk_is_distinguished(monkeypatch, tmp_path):
    monkeypatch.setattr(V, "_jellyfin", fake_items([
        {"Id": "1", "Name": "Gone", "Type": "Movie", "Path": str(tmp_path / "gone.mkv")},
    ]))
    d = T.video_play("gone")
    assert d["error"] == "missing_file" and "Gone" in d["message"]


def test_tools_never_raise(monkeypatch):
    """A broken library must come back as an error dict, not an exception
    thrown into the middle of a voice session."""
    def boom(*a, **k):
        raise RuntimeError("jellyfin exploded")

    monkeypatch.setattr(V, "search", boom)
    for call in (lambda: T.video_play("x"), lambda: T.video_search("x")):
        d = call()
        assert d["ok"] is False and "RuntimeError" in d["error"]


def test_stopping_survives_a_player_that_will_not_die(monkeypatch):
    class Stubborn:
        def poll(self):
            return None

        def terminate(self):
            raise OSError("access denied")

    monkeypatch.setattr(V, "_process", Stubborn())
    assert V.stop() is True          # reported, not raised
    assert V.is_playing() is False   # and no longer considered playing
