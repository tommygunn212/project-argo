"""Spoken names carry no punctuation, and nobody says the whole title.

Tommy could not get T. Rex to play. The index held 17 of their tracks under
'T. Rex', 'T.Rex' and 'Marc Bolan & T. Rex'; matching was
LOWER(name) = LOWER(?), so:

    artist='T. Rex'                 -> 5 rows
    artist='t rex'                  -> 0 rows   <- what speech produces
    title='Bang a Gong (Get It On)' -> 2 rows
    title='Bang a Gong'             -> 0 rows   <- nobody says the bracket
"""

import sqlite3

import pytest

from core.database import MIN_SUBSTRING_MATCH, MusicDatabase, _squash


@pytest.fixture
def library(tmp_path):
    """A small library with the punctuation that broke the real one."""
    db = tmp_path / "music.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE artists (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
                              sovereignty_rank INTEGER DEFAULT 0);
        CREATE TABLE albums  (id INTEGER PRIMARY KEY, artist_id INTEGER, title TEXT, year INTEGER);
        CREATE TABLE tracks  (id INTEGER PRIMARY KEY, album_id INTEGER, title TEXT,
                              year INTEGER, duration INTEGER, path TEXT);
        CREATE TABLE genres  (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
        CREATE TABLE track_genres (track_id INTEGER, genre_id INTEGER,
                                   PRIMARY KEY (track_id, genre_id));
        CREATE TABLE genre_adjacency (genre_id INTEGER, adjacent_genre_id INTEGER,
                                      PRIMARY KEY (genre_id, adjacent_genre_id));
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE ingest_anomalies (jellyfin_id TEXT PRIMARY KEY, issue TEXT,
                                       raw_name TEXT, path TEXT);
        CREATE INDEX idx_tracks_title ON tracks(title);
        CREATE INDEX idx_tracks_year ON tracks(year);
        CREATE INDEX idx_artists_name ON artists(name);
        CREATE INDEX idx_genres_name ON genres(name);
        """
    )
    data = [
        ("T. Rex", "Electric Warrior", "Bang a Gong (Get It On)", 1971),
        ("T. Rex", "Electric Warrior", "Metal Guru", 1972),
        ("Marc Bolan & T. Rex", "Greatest", "I Love to Boogie", 1976),
        ("The Clash", "London Calling", "London Calling", 1979),
        ("AC/DC", "Back in Black", "Back in Black", 1980),
        ("Blue Öyster Cult", "Agents", "Don't Fear the Reaper", 1976),
    ]
    for artist, album, title, year in data:
        con.execute("INSERT OR IGNORE INTO artists (name) VALUES (?)", (artist,))
        aid = con.execute("SELECT id FROM artists WHERE name = ?", (artist,)).fetchone()[0]
        con.execute("INSERT INTO albums (artist_id, title, year) VALUES (?, ?, ?)",
                    (aid, album, year))
        alid = con.execute("SELECT MAX(id) FROM albums").fetchone()[0]
        con.execute("INSERT INTO tracks (album_id, title, year, path) VALUES (?, ?, ?, ?)",
                    (alid, title, year, f"C:/music/{title}.mp3"))
    con.commit()
    con.close()
    return MusicDatabase(db)


# --- the normaliser -------------------------------------------------------

@pytest.mark.parametrize("said,expected", [
    ("T. Rex", "trex"), ("t rex", "trex"), ("T.Rex", "trex"), ("TREX", "trex"),
    ("AC/DC", "acdc"), ("Blue Öyster Cult", "blueöystercult"),
    ("Bang a Gong (Get It On)", "bangagonggetiton"),
])
def test_squash_removes_what_speech_never_carries(said, expected):
    assert _squash(said) == expected


def test_squash_survives_none():
    assert _squash(None) == ""


# --- the regression -------------------------------------------------------

@pytest.mark.parametrize("spelling", ["T. Rex", "T.Rex", "t rex", "trex", "T REX"])
def test_every_spelling_of_t_rex_finds_t_rex(library, spelling):
    rows = library.query_tracks(artist=spelling, limit=10)
    assert rows, f"{spelling!r} found nothing"
    assert any("rex" in r["artist"].lower() for r in rows)


def test_a_partial_title_matches(library):
    """'Bang a Gong' has to reach 'Bang a Gong (Get It On)'."""
    rows = library.query_tracks(title="Bang a Gong", limit=10)
    assert len(rows) == 1
    assert rows[0]["song"] == "Bang a Gong (Get It On)"


def test_the_artist_search_also_reaches_collaborations(library):
    rows = library.query_tracks(artist="t rex", limit=10)
    names = {r["artist"] for r in rows}
    assert "T. Rex" in names and "Marc Bolan & T. Rex" in names


def test_a_slash_in_the_name_is_not_a_problem(library):
    assert library.query_tracks(artist="acdc", limit=5)
    assert library.query_tracks(artist="AC DC", limit=5)


# --- it must not become a free-for-all ------------------------------------

def test_an_unknown_artist_still_finds_nothing(library):
    assert library.query_tracks(artist="zzzqqq not a band", limit=5) == []


def test_very_short_queries_do_not_match_everything(library):
    """A two-letter substring would drag in half the library."""
    assert len(_squash("ac")) < MIN_SUBSTRING_MATCH
    rows = library.query_tracks(artist="ac", limit=50)
    assert rows == [], "a two-character query must stay exact"


def test_an_exact_match_sorts_above_a_partial_one(library):
    """Asking for The Clash should not lead with a collaboration."""
    rows = library.query_tracks(artist="T. Rex", limit=10)
    assert rows[0]["artist"] == "T. Rex"
