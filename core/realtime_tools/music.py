"""The music library and player - and the truth about whether it is playing.

Launching a player is not playing. Every play path here waits and checks,
because ARGO once announced tracks for weeks into silence.
"""

from __future__ import annotations

import random
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

from core.realtime_tools._base import capability, ROOT, logger

__all__ = [
    "music_play",
    "PLAYBACK_SETTLE_SECONDS",
    "parse_era",
    "music_play_era",
    "music_stop",
    "music_next",
    "music_status",
    "music_library_status",
]


_PLAY_KINDS = {"song", "artist", "genre", "keyword", "random"}


@capability
def music_play(query: str = "", kind: str = "keyword") -> dict:
    """Start music. kind is song, artist, genre, keyword or random."""
    from core.music_player import get_music_player

    kind = (kind or "keyword").strip().lower()
    if kind not in _PLAY_KINDS:
        kind = "keyword"
    player = get_music_player()
    if kind == "random" or not query.strip():
        started = player.play_random()
        kind = "random"
    else:
        started = {
            "song": player.play_by_song,
            "artist": player.play_by_artist,
            "genre": player.play_by_genre,
            "keyword": player.play_by_keyword,
        }[kind](query)
    if not started:
        return {
            "ok": False,
            "error": "no_match",
            "kind": kind,
            "query": query,
            "playing": False,
            "message": f"Nothing matched {query!r}.",
        }
    return _confirm_playing(player, kind=kind, query=query)


# How long to wait before believing that playback started. A stream that
# 404s kills ffplay in well under this; a stream that works is still going.
PLAYBACK_SETTLE_SECONDS = 1.2


def _confirm_playing(player, *, kind: str, query: str) -> dict:
    """Report what is actually coming out of the speakers.

    Launching a player is not playing. When the source 404s, ffplay exits
    with code 0 before anyone looks, and ARGO used to announce the track
    anyway - which is how Tommy was told music was playing in silence.
    """
    track = {}
    try:
        track = dict(getattr(player, "current_track", {}) or {})
    except Exception:
        track = {}

    time.sleep(PLAYBACK_SETTLE_SECONDS)

    try:
        playing = bool(player.is_playing())
    except Exception:
        logger.debug("[Tools] is_playing failed", exc_info=True)
        playing = False

    song = track.get("song") or track.get("title")
    artist = track.get("artist")
    named = " - ".join(p for p in (artist, song) if p) or "the track"

    if playing:
        return {"ok": True, "kind": kind, "query": query, "playing": True,
                "track": {"artist": artist, "song": song},
                "message": f"Playing {named}."}

    return {
        "ok": False,
        "error": "playback_died",
        "kind": kind,
        "query": query,
        "playing": False,
        "track": {"artist": artist, "song": song},
        "message": (
            f"I found {named} and started it, but playback stopped immediately - "
            "no sound is coming out. The track is in ARGO's index but the "
            "media server could not serve it."
        ),
    }


_DECADE_WORDS = {
    "twenties": 1920, "thirties": 1930, "forties": 1940, "fifties": 1950,
    "sixties": 1960, "seventies": 1970, "eighties": 1980, "nineties": 1990,
    "noughties": 2000, "two thousands": 2000, "tens": 2010, "twenty tens": 2010,
}


def parse_era(era: str) -> Optional[tuple]:
    """Turn a spoken era into a (year_start, year_end) range.

    Handles "80s", "1980s", "the eighties", "1975", "1975 to 1980". Bare
    two-digit decades below 30 are read as 2000s, so "20s" is 2020 not 1920 -
    ask for "the roaring twenties" era by year if you mean the other one.
    """
    text = (era or "").strip().lower().replace("'", "").replace("the ", "")
    if not text:
        return None

    span = re.search(r"(\d{4})\s*(?:to|-|until|through)\s*(\d{4})", text)
    if span:
        a, b = int(span.group(1)), int(span.group(2))
        return (min(a, b), max(a, b))

    for word, start in _DECADE_WORDS.items():
        if word in text:
            return (start, start + 9)

    decade = re.search(r"(\d{2,4})\s*s\b", text)
    if decade:
        raw = decade.group(1)
        year = int(raw)
        if len(raw) == 2:
            year = 2000 + year if year < 30 else 1900 + year
        year = (year // 10) * 10
        return (year, year + 9)

    single = re.search(r"\b(\d{4})\b", text)
    if single:
        y = int(single.group(1))
        return (y, y)

    return None


@capability
def music_play_era(era: str, genre: str = "", artist: str = "") -> dict:
    """Play music from a period, optionally narrowed by genre or artist.

    The track database already stores a year and query_tracks accepts
    year_start/year_end; nothing exposed it, so era was not something that
    could be asked for.
    """
    rng = parse_era(era)
    if not rng:
        return {"ok": False, "error": "unparsed_era",
                "message": f"I couldn't work out what period {era!r} means."}
    year_start, year_end = rng

    from core.music_player import MusicDatabase, get_music_player

    tracks = MusicDatabase().query_tracks(
        year_start=year_start,
        year_end=year_end,
        genre=genre or None,
        artist=artist or None,
        limit=200,
    ) or []
    if not tracks:
        return {"ok": False, "error": "no_matches", "era": era,
                "years": [year_start, year_end],
                "message": f"I have nothing from {year_start} to {year_end}"
                           + (f" by {artist}" if artist else "")
                           + (f" in {genre}" if genre else "") + "."}

    pick = random.choice(tracks)
    player = get_music_player()
    path = pick.get("path") or pick.get("file_path") or pick.get("track_path")
    # query_tracks returns the track name under "song", not "title".
    title = pick.get("song") or pick.get("title") or pick.get("name") or "that"
    started = player.play(path, title, track_data=pick) if path else False
    if not started:
        return {"ok": False, "error": "no_match", "era": era,
                "years": [year_start, year_end], "matches": len(tracks),
                "playing": False,
                "message": f"I could not start {title}."}
    result = _confirm_playing(player, kind="era", query=era)
    result.update({
        "era": era,
        "years": [year_start, year_end],
        "matches": len(tracks),
        "now_playing": {"title": title, "artist": pick.get("artist"), "year": pick.get("year")},
    })
    return result


@capability
def music_stop() -> dict:
    from core.music_player import get_music_player

    get_music_player().stop()
    return {"ok": True, "playing": False}


@capability
def music_next() -> dict:
    from core.music_player import get_music_player

    player = get_music_player()
    return {"ok": bool(player.play_next()), "playing": player.is_playing()}


@capability
def music_status() -> dict:
    from core.music_player import get_music_player, get_playback_state

    state = get_playback_state()
    now = getattr(state, "current_track", None) or getattr(state, "track_name", None)
    return {"ok": True, "playing": get_music_player().is_playing(), "now_playing": now}


@capability
def music_library_status(sample: int = 60) -> dict:
    """Is the music index still true? Where the library is, and whether it plays.

    The index drifted from the library once already - thousands of tracks
    were announced for weeks while every one of them 404'd, because nothing
    ever checked the index against reality. This checks.
    """
    from core.music_player import MUSIC_DB_PATH

    db = ROOT / MUSIC_DB_PATH
    if not db.exists():
        return {"ok": False, "error": "no_library",
                "message": "There is no music library indexed."}

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        total = con.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
        streamed = con.execute(
            "SELECT COUNT(*) FROM tracks WHERE path LIKE 'jellyfin://%'"
        ).fetchone()[0]
        rows = con.execute(
            "SELECT path FROM tracks WHERE path NOT LIKE 'jellyfin://%' "
            "ORDER BY RANDOM() LIMIT ?", (max(1, min(500, int(sample))),)
        ).fetchall()
    finally:
        con.close()

    checked = [r[0] for r in rows]
    missing = [p for p in checked if not Path(p).exists()]
    healthy = not missing and not streamed

    result = {
        "ok": True,
        "tracks": total,
        "source": meta.get("source", "unknown"),
        "root": meta.get("root"),
        "indexed_at": meta.get("ingested_at"),
        "checked": len(checked),
        "missing_from_disk": len(missing),
        "streamed_from_server": streamed,
        "healthy": healthy,
    }
    if streamed:
        result["message"] = (
            f"{streamed} of {total} tracks are server streams rather than files. "
            "If the server no longer has them they will announce and then fall silent."
        )
    elif missing:
        result["examples"] = missing[:3]
        result["message"] = (
            f"{len(missing)} of the {len(checked)} tracks I checked are indexed but "
            f"missing from disk. The library may have moved - it needs re-indexing."
        )
    else:
        result["message"] = f"{total} tracks indexed from {meta.get('root')}, and they are there."
    return result
