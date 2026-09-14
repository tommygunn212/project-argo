"""ARGO should be able to tell when its index has outlived the library.

9,990 tracks were offered and announced for weeks while every one of them
404'd. Nothing in ARGO could notice, because nothing ever compared the index
against reality.
"""

import sqlite3

import pytest

from core import realtime_tools as T


def build(tmp_path, rows, meta=None):
    db = tmp_path / "music.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE tracks (id INTEGER PRIMARY KEY, path TEXT)")
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    con.executemany("INSERT INTO tracks (path) VALUES (?)", [(p,) for p in rows])
    con.executemany("INSERT INTO meta (key, value) VALUES (?, ?)",
                    list((meta or {}).items()))
    con.commit()
    con.close()
    return db


@pytest.fixture
def library(tmp_path, monkeypatch):
    def _make(rows, meta=None):
        db = build(tmp_path, rows, meta)
        monkeypatch.setattr(T, "ROOT", tmp_path)
        monkeypatch.setattr("core.music_player.MUSIC_DB_PATH", "music.db")
        return db
    return _make


def test_a_healthy_local_library_reports_healthy(library, tmp_path):
    files = []
    for n in range(5):
        f = tmp_path / f"song{n}.mp3"
        f.write_bytes(b"x")
        files.append(str(f))
    library(files, {"source": "local", "root": str(tmp_path), "ingested_at": "now"})

    d = T.music_library_status()

    assert d["ok"] and d["healthy"] is True
    assert d["tracks"] == 5 and d["missing_from_disk"] == 0
    assert str(tmp_path) in d["message"]


def test_files_that_vanished_are_counted_and_named(library, tmp_path):
    kept = tmp_path / "kept.mp3"
    kept.write_bytes(b"x")
    library([str(kept), str(tmp_path / "gone1.mp3"), str(tmp_path / "gone2.mp3")],
            {"source": "local", "root": str(tmp_path)})

    d = T.music_library_status()

    assert d["healthy"] is False
    assert d["missing_from_disk"] == 2
    assert len(d["examples"]) == 2
    assert "needs re-indexing" in d["message"]


def test_server_streams_are_flagged_as_the_risk_they_are(library, tmp_path):
    """This is the state the library was actually in: every path a stream,
    and the server no longer holding them."""
    library([f"jellyfin://{n}" for n in range(9990)], {"source": "jellyfin"})

    d = T.music_library_status()

    assert d["healthy"] is False
    assert d["streamed_from_server"] == 9990
    assert "fall silent" in d["message"]


def test_no_library_at_all_is_reported_plainly(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "ROOT", tmp_path)
    monkeypatch.setattr("core.music_player.MUSIC_DB_PATH", "absent.db")

    d = T.music_library_status()

    assert d["ok"] is False and d["error"] == "no_library"


def test_it_never_raises(monkeypatch):
    monkeypatch.setattr("core.music_player.MUSIC_DB_PATH", 12345)  # nonsense
    d = T.music_library_status()
    assert d["ok"] is False
