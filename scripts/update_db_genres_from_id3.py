"""
Update music.db genres from ID3 tags.

- Reads all tracks from data/music.db
- Loads ID3 genre tags from files on disk
- Normalizes + de-duplicates genre names
- Inserts/links genres in genres + track_genres tables

Usage:
    I:/argo/.venv/Scripts/python.exe scripts/update_db_genres_from_id3.py
    I:/argo/.venv/Scripts/python.exe scripts/update_db_genres_from_id3.py --replace
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, List, Optional

from mutagen.easyid3 import EasyID3

# Ensure repo root is on sys.path for core imports
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.music_index import GENRE_ALIASES

DB_PATH = "data/music.db"

SPLIT_RE = re.compile(r"[;,/]")


def _normalize_genre(value: str) -> Optional[str]:
    if not value:
        return None
    cleaned = value.strip().lower().replace("_", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return None
    if cleaned in GENRE_ALIASES:
        return GENRE_ALIASES[cleaned]
    return cleaned


def _expand_genres(raw: Iterable[str]) -> List[str]:
    out: List[str] = []
    for entry in raw:
        if not entry:
            continue
        parts = SPLIT_RE.split(entry)
        for part in parts:
            norm = _normalize_genre(part)
            if norm:
                out.append(norm)
    # De-duplicate while preserving order
    seen = set()
    unique = []
    for g in out:
        if g in seen:
            continue
        seen.add(g)
        unique.append(g)
    return unique


def update_db(replace_existing: bool = False) -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("SELECT id, name FROM genres")
    genre_map = {name: gid for gid, name in cur.fetchall()}

    cur.execute("SELECT id, path FROM tracks")
    rows = cur.fetchall()

    total_tracks = 0
    updated_tracks = 0
    linked = 0
    skipped = 0
    missing = 0

    for track_id, path_str in rows:
        total_tracks += 1
        path = Path(path_str)
        if not path.exists() or path.suffix.lower() != ".mp3":
            missing += 1
            continue

        try:
            audio = EasyID3(str(path))
        except Exception:
            skipped += 1
            continue

        raw_genres = audio.get("genre", [])
        genres = _expand_genres(raw_genres)
        if not genres:
            skipped += 1
            continue

        if replace_existing:
            cur.execute("DELETE FROM track_genres WHERE track_id = ?", (track_id,))

        for name in genres:
            gid = genre_map.get(name)
            if gid is None:
                cur.execute("INSERT OR IGNORE INTO genres(name) VALUES (?)", (name,))
                cur.execute("SELECT id FROM genres WHERE name = ?", (name,))
                row = cur.fetchone()
                if row:
                    gid = row[0]
                    genre_map[name] = gid

            if gid is not None:
                cur.execute(
                    "INSERT OR IGNORE INTO track_genres(track_id, genre_id) VALUES (?, ?)",
                    (track_id, gid),
                )
                linked += 1

        updated_tracks += 1

    con.commit()
    con.close()

    print("[DB] Genre sync complete")
    print(f"  Tracks scanned: {total_tracks}")
    print(f"  Tracks updated: {updated_tracks}")
    print(f"  Genre links:    {linked}")
    print(f"  Skipped:        {skipped}")
    print(f"  Missing/non-mp3:{missing}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update music.db genres from ID3 tags")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing genre links for each track before adding ID3 genres",
    )
    args = parser.parse_args()
    update_db(replace_existing=args.replace)
