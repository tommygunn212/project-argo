"""Index a local music folder into ARGO's library database.

Tommy's music left the Jellyfin server: the server reports SongCount 1,
ArtistCount 0, AlbumCount 0, and only Movies/TV/Collections libraries. The
files are still on disk. This reads them directly, so the library works with
no media server in the middle and nothing to 404.

It fills the same schema the Jellyfin ingest fills, so every existing query -
artist, genre, era, sovereignty, adjacency - keeps working untouched. The
only difference is that `tracks.path` holds a real file path instead of a
jellyfin:// URI, which core.music_player now plays directly.

    python scripts/ingest_local_music.py "I:\\My Music"
    python scripts/ingest_local_music.py "I:\\My Music" --dry-run
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

AUDIO_SUFFIXES = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".wav", ".alac", ".aiff"}

# "03 - artist - title", "07 title", "artist - title"
LEADING_TRACK_NUMBER = re.compile(r"^\s*\(?\d{1,3}\)?[\s._-]+")


def clean(value) -> str:
    """Tag values arrive as lists, bytes, or padded strings."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    text = str(value).strip().strip("\x00")
    return re.sub(r"\s+", " ", text)


def year_of(value) -> int | None:
    match = re.search(r"(19|20)\d{2}", clean(value))
    return int(match.group()) if match else None


def from_filename(path: Path) -> tuple[str, str]:
    """Fall back to 'artist - title' in the filename when tags are missing.

    Most of this library is named that way, so it recovers far more than it
    invents. Anything genuinely ambiguous stays Unknown rather than guessing.
    """
    stem = LEADING_TRACK_NUMBER.sub("", path.stem)
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return clean(artist), clean(title)
    return "", clean(stem)


def read_tags(path: Path) -> dict:
    artist = album = title = genre = ""
    year = None
    duration = None
    try:
        import mutagen

        audio = mutagen.File(path, easy=True)
        if audio is not None:
            tags = audio.tags or {}
            artist = clean(tags.get("albumartist") or tags.get("artist"))
            album = clean(tags.get("album"))
            title = clean(tags.get("title"))
            genre = clean(tags.get("genre"))
            year = year_of(tags.get("date") or tags.get("originaldate") or tags.get("year"))
            info = getattr(audio, "info", None)
            if info is not None and getattr(info, "length", None):
                duration = int(info.length)
    except Exception:
        pass

    file_artist, file_title = from_filename(path)
    if not title:
        title = file_title
    if not artist:
        artist = file_artist
    if not album:
        album = clean(path.parent.name)

    return {
        "artist": artist or "Unknown Artist",
        "album": album or "Unknown Album",
        "title": title or path.stem,
        "genre": genre.lower() if genre else "",
        "year": year,
        "duration": duration,
        "path": str(path),
    }


def scan(root: Path):
    for path in root.rglob("*"):
        if path.suffix.lower() in AUDIO_SUFFIXES and path.is_file():
            yield path


def ingest(root: Path, db_path: Path, dry_run: bool = False) -> dict:
    from core.music_player import KNOWN_ARTISTS, MusicDatabase

    files = list(scan(root))
    print(f"found {len(files)} audio files under {root}")
    if dry_run:
        for path in files[:10]:
            tags = read_tags(path)
            print(f"   {tags['artist']} - {tags['title']} ({tags['year'] or '----'}) [{tags['genre'] or 'no genre'}]")
        return {"files": len(files), "written": 0, "dry_run": True}

    # Write to a side file, then swap. A half-written library is worse than
    # the stale one it replaces.
    staging = db_path.with_suffix(".rebuilding.db")
    staging.unlink(missing_ok=True)
    con = sqlite3.connect(str(staging))
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
        -- core.database.validate_schema refuses to open a library that is
        -- missing any of these, so the set here must match it exactly.
        CREATE INDEX idx_tracks_title ON tracks(title);
        CREATE INDEX idx_tracks_year ON tracks(year);
        CREATE INDEX idx_artists_name ON artists(name);
        CREATE INDEX idx_genres_name ON genres(name);
        CREATE INDEX idx_tracks_album ON tracks(album_id);
        CREATE INDEX idx_albums_artist ON albums(artist_id);
        """
    )

    artist_ids: dict[str, int] = {}
    album_ids: dict[tuple, int] = {}
    genre_ids: dict[str, int] = {}
    written = 0
    started = time.time()

    for n, path in enumerate(files, 1):
        tags = read_tags(path)

        artist = tags["artist"]
        if artist not in artist_ids:
            cur = con.execute("INSERT OR IGNORE INTO artists (name) VALUES (?)", (artist,))
            artist_ids[artist] = cur.lastrowid or con.execute(
                "SELECT id FROM artists WHERE name = ?", (artist,)).fetchone()[0]

        key = (artist_ids[artist], tags["album"])
        if key not in album_ids:
            cur = con.execute("INSERT INTO albums (artist_id, title, year) VALUES (?, ?, ?)",
                              (artist_ids[artist], tags["album"], tags["year"]))
            album_ids[key] = cur.lastrowid

        cur = con.execute(
            "INSERT INTO tracks (album_id, title, year, duration, path) VALUES (?, ?, ?, ?, ?)",
            (album_ids[key], tags["title"], tags["year"], tags["duration"], tags["path"]),
        )
        track_id = cur.lastrowid
        written += 1

        for genre in [g for g in re.split(r"[;,/]", tags["genre"]) if g.strip()]:
            genre = genre.strip().lower()
            if genre not in genre_ids:
                con.execute("INSERT OR IGNORE INTO genres (name) VALUES (?)", (genre,))
                genre_ids[genre] = con.execute(
                    "SELECT id FROM genres WHERE name = ?", (genre,)).fetchone()[0]
            con.execute("INSERT OR IGNORE INTO track_genres (track_id, genre_id) VALUES (?, ?)",
                        (track_id, genre_ids[genre]))

        if n % 1000 == 0:
            con.commit()
            print(f"   {n}/{len(files)} ({time.time() - started:.0f}s)")

    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('source', 'local')")
    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('root', ?)", (str(root),))
    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('ingested_at', ?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"),))
    con.commit()

    for name, rank in ((a, 10) for a in KNOWN_ARTISTS):
        con.execute("UPDATE artists SET sovereignty_rank = ? WHERE lower(name) = lower(?)",
                    (rank, name))
    con.commit()
    con.close()

    backup = db_path.with_suffix(f".jellyfin-backup-{time.strftime('%Y%m%d-%H%M%S')}.db")
    try:
        if db_path.exists():
            db_path.replace(backup)
            print(f"previous library kept at {backup.name}")
        staging.replace(db_path)
    except PermissionError:
        # ARGO holds the library open while it is running. The scan is
        # finished and safe on disk; say exactly how to finish the swap
        # rather than losing 4 minutes of work to a locked file.
        print(
            f"\nThe new library is built and complete at:\n"
            f"    {staging}\n"
            f"but {db_path.name} is locked, which means ARGO is running.\n"
            f"Stop ARGO, then rename {staging.name} to {db_path.name}."
        )
        return {"files": len(files), "written": written, "artists": len(artist_ids),
                "albums": len(album_ids), "genres": len(genre_ids),
                "staged_at": str(staging), "swapped": False}

    return {"files": len(files), "written": written, "artists": len(artist_ids),
            "albums": len(album_ids), "genres": len(genre_ids), "db": str(db_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="folder to index, e.g. I:\\My Music")
    parser.add_argument("--db", default=None, help="library database (default: ARGO's own)")
    parser.add_argument("--dry-run", action="store_true", help="report what would be indexed")
    args = parser.parse_args()

    from core.music_player import MUSIC_DB_PATH

    root = Path(args.root)
    if not root.is_dir():
        print(f"not a folder: {root}")
        return 1
    db_path = Path(args.db) if args.db else (ROOT / MUSIC_DB_PATH)

    result = ingest(root, db_path, dry_run=args.dry_run)
    print("\n" + ", ".join(f"{k}={v}" for k, v in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
