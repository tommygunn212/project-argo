"""
SQLite Music Database (Read-Optimized)

Atomic initialization and lightweight ingest for music lookups.
"""

import os
import sqlite3
import threading
import logging
import tempfile
import time
import functools
import re
from pathlib import Path
from typing import Iterable, Optional, Dict, List, Tuple

from core.config import MUSIC_DB_PATH, AUTO_INIT_DB

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(MUSIC_DB_PATH)
EXPECTED_SCHEMA_VERSION = "1.0"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS artists (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    sovereignty_rank INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY,
    artist_id INTEGER,
    title TEXT,
    year INTEGER
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    album_id INTEGER,
    title TEXT,
    year INTEGER,
    duration INTEGER,
    path TEXT
);

CREATE TABLE IF NOT EXISTS genres (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS track_genres (
    track_id INTEGER,
    genre_id INTEGER,
    PRIMARY KEY (track_id, genre_id)
);

CREATE TABLE IF NOT EXISTS ingest_anomalies (
    jellyfin_id TEXT PRIMARY KEY,
    issue TEXT,
    raw_name TEXT,
    path TEXT
);

CREATE TABLE IF NOT EXISTS genre_adjacency (
    genre_id INTEGER,
    adjacent_genre_id INTEGER,
    PRIMARY KEY (genre_id, adjacent_genre_id)
);

CREATE INDEX IF NOT EXISTS idx_tracks_title ON tracks(title);
CREATE INDEX IF NOT EXISTS idx_artists_name ON artists(name);
CREATE INDEX IF NOT EXISTS idx_genres_name ON genres(name);
CREATE INDEX IF NOT EXISTS idx_tracks_year ON tracks(year);
"""

_DEFAULT_GENRE_ADJACENCY = {
    "punk": ["rock", "new wave", "alternative"],
    "rock": ["punk", "metal", "classic rock"],
    "metal": ["rock", "punk", "alternative"],
    "pop": ["soul", "r&b", "indie"],
    "rap": ["soul", "r&b", "funk"],
    "jazz": ["soul", "blues", "funk"],
    "soul": ["r&b", "jazz", "funk"],
    "blues": ["jazz", "soul", "folk"],
    "country": ["folk", "americana", "bluegrass"],
    "folk": ["country", "blues", "singer-songwriter"],
    "electronic": ["house", "techno", "ambient"],
    "house": ["electronic", "techno", "funk"],
    "indie": ["alternative", "pop", "rock"],
    "alternative": ["indie", "rock", "punk"],
}


def music_db_exists(path: str) -> bool:
    db_path = Path(path)
    if not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path.exists()


def init_schema(path: str) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        cur = conn.cursor()
        cur.execute("SELECT value FROM meta WHERE key = ?", ("schema_version",))
        row = cur.fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?)",
                ("schema_version", EXPECTED_SCHEMA_VERSION),
            )
            conn.commit()
        elif row[0] != EXPECTED_SCHEMA_VERSION:
            raise RuntimeError(
                f"[DB] Schema version mismatch: expected {EXPECTED_SCHEMA_VERSION}, found {row[0]}"
            )

        cur.execute("SELECT COUNT(*) FROM genre_adjacency")
        count = cur.fetchone()[0]
        if not count:
            for genre, adjacents in _DEFAULT_GENRE_ADJACENCY.items():
                cur.execute("INSERT OR IGNORE INTO genres(name) VALUES (?)", (genre,))
                cur.execute("SELECT id FROM genres WHERE name = ?", (genre,))
                genre_id = cur.fetchone()[0]
                for adjacent in adjacents:
                    cur.execute("INSERT OR IGNORE INTO genres(name) VALUES (?)", (adjacent,))
                    cur.execute("SELECT id FROM genres WHERE name = ?", (adjacent,))
                    adjacent_id = cur.fetchone()[0]
                    cur.execute(
                        "INSERT OR IGNORE INTO genre_adjacency(genre_id, adjacent_genre_id) VALUES (?, ?)",
                        (genre_id, adjacent_id),
                    )
            conn.commit()
    finally:
        conn.close()


def get_db_status(path: str) -> Dict[str, object]:
    status = {
        "present": False,
        "indexed": False,
        "track_count": 0,
        "last_ingest_time": None,
    }

    if not music_db_exists(path):
        return status

    status["present"] = True
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM tracks")
        track_count = cur.fetchone()[0]
        status["track_count"] = int(track_count)
        status["indexed"] = int(track_count) > 0
        cur.execute("SELECT value FROM meta WHERE key = ?", ("last_ingest_time",))
        row = cur.fetchone()
        status["last_ingest_time"] = row[0] if row else None
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return status


def _normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned


def normalize_title(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = value.lower()
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    cleaned = re.sub(r"\b(the|a|an)\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned.endswith("s"):
        cleaned = cleaned[:-1]
    cleaned = cleaned.strip()
    return cleaned or None


def _normalize_title_for_match(value: Optional[str]) -> Optional[str]:
    return normalize_title(value)


def _atomic_initialize_db(db_path: Path) -> None:
    if not AUTO_INIT_DB:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        return

    with tempfile.NamedTemporaryFile(dir=db_path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        conn = sqlite3.connect(tmp_path)
        try:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()
        os.replace(tmp_path, db_path)
        logger.info("[DB] Initialized sqlite database at %s", db_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


class MusicDatabase:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._cached_query = functools.lru_cache(maxsize=64)(self._query_tracks_uncached)

    def _ensure_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            if not music_db_exists(str(self.db_path)):
                raise RuntimeError("Music DB not present")
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA foreign_keys = ON")
            self.validate_schema()
            self._cached_query.cache_clear()
        return self._conn

    def validate_schema(self) -> None:
        if self._conn is None:
            conn = sqlite3.connect(self.db_path)
            should_close = True
        else:
            conn = self._conn
            should_close = False
        try:
            expected_columns = {
                "artists": {"id", "name", "sovereignty_rank"},
                "albums": {"id", "artist_id", "title", "year"},
                "tracks": {"id", "album_id", "title", "year", "duration", "path"},
                "genres": {"id", "name"},
                "track_genres": {"track_id", "genre_id"},
                "genre_adjacency": {"genre_id", "adjacent_genre_id"},
                "ingest_anomalies": {"jellyfin_id", "issue", "raw_name", "path"},
            }
            expected_indexes = {
                "tracks": {"idx_tracks_title", "idx_tracks_year"},
                "artists": {"idx_artists_name"},
                "genres": {"idx_genres_name"},
            }

            cur = conn.cursor()
            for table, columns in expected_columns.items():
                cur.execute(f"PRAGMA table_info({table})")
                actual = {row[1] for row in cur.fetchall()}
                if actual != columns:
                    raise RuntimeError(
                        f"[DB] Schema mismatch for {table}: expected {sorted(columns)} got {sorted(actual)}"
                    )

            for table, indexes in expected_indexes.items():
                cur.execute(f"PRAGMA index_list({table})")
                actual_indexes = {row[1] for row in cur.fetchall()}
                missing = indexes - actual_indexes
                if missing:
                    raise RuntimeError(
                        f"[DB] Missing indexes on {table}: {sorted(missing)}"
                    )
        finally:
            if should_close:
                conn.close()


    def _execute(self, sql: str, params: Tuple = ()) -> sqlite3.Cursor:
        if not music_db_exists(str(self.db_path)):
            return {"ingested": 0, "skipped": 0, "errors": 0}

        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur

    def _executemany(self, sql: str, params: Iterable[Tuple]) -> None:
        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            cur.executemany(sql, params)
            conn.commit()

    def set_artist_sovereignty(self, artists: Iterable[str], rank: int = 5) -> None:
        normalized = {_normalize_text(a) for a in artists}
        values = [(name, rank) for name in normalized if name]
        if not values:
            return
        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            for name, value in values:
                cur.execute(
                    "INSERT OR IGNORE INTO artists(name, sovereignty_rank) VALUES (?, ?)",
                    (name, value),
                )
                cur.execute(
                    "UPDATE artists SET sovereignty_rank = MAX(sovereignty_rank, ?) WHERE name = ?",
                    (value, name),
                )
            conn.commit()

    def ingest_jellyfin_tracks(self, tracks: List[Dict], incremental: bool = True) -> Dict[str, int]:
        if not tracks:
            return {"ingested": 0, "skipped": 0, "errors": 0}

        conn = self._ensure_connection()
        existing_paths = set()
        if incremental:
            with self._lock:
                cur = conn.cursor()
                cur.execute("SELECT path FROM tracks")
                existing_paths = {row[0] for row in cur.fetchall() if row[0]}

        ingested = 0
        skipped = 0
        errors = 0

        junk_artist = {"unknown artist", "unknown"}
        if not incremental:
            self._cached_query.cache_clear()

        with self._lock:
            cur = conn.cursor()
            for track in tracks:
                try:
                    artist_name = _normalize_text(track.get("artist"))
                    if artist_name and artist_name.lower() in junk_artist:
                        artist_name = None
                    if not artist_name:
                        artist_name = "Unknown Artist"
                    title = _normalize_text(track.get("song")) or _normalize_text(track.get("name"))
                    album_title = _normalize_text(track.get("album"))
                    year = track.get("year")
                    duration = track.get("duration")
                    jellyfin_id = track.get("jellyfin_id") or track.get("jellyfin_item_id")
                    genres = track.get("genres") or []
                    if not isinstance(genres, list):
                        genres = [genres]
                    if not genres:
                        genres = [track.get("genre")]
                    normalized_genres = []
                    for genre_value in genres:
                        cleaned = _normalize_text(genre_value)
                        if cleaned and cleaned not in normalized_genres:
                            normalized_genres.append(cleaned)

                    if not title or not jellyfin_id:
                        logger.warning(
                            "[DB] Ingest error: missing title or jellyfin_id (title=%s, jellyfin_id=%s)",
                            title,
                            jellyfin_id,
                        )
                        errors += 1
                        continue

                    path = f"jellyfin://{jellyfin_id}"
                    def apply_genres(target_track_id: int) -> None:
                        if not normalized_genres:
                            return
                        cur.execute("DELETE FROM track_genres WHERE track_id = ?", (target_track_id,))
                        for genre in normalized_genres:
                            if genre.lower() in ("unknown", "unknown genre"):
                                continue
                            cur.execute("INSERT OR IGNORE INTO genres(name) VALUES (?)", (genre,))
                            cur.execute("SELECT id FROM genres WHERE name = ?", (genre,))
                            genre_id = cur.fetchone()[0]
                            cur.execute(
                                "INSERT OR IGNORE INTO track_genres(track_id, genre_id) VALUES (?, ?)",
                                (target_track_id, genre_id),
                            )

                    if incremental and path in existing_paths:
                        cur.execute("SELECT id FROM tracks WHERE path = ?", (path,))
                        row = cur.fetchone()
                        if row:
                            apply_genres(row[0])
                        skipped += 1
                        continue

                    cur.execute("INSERT OR IGNORE INTO artists(name) VALUES (?)", (artist_name,))
                    cur.execute("SELECT id FROM artists WHERE name = ?", (artist_name,))
                    artist_id = cur.fetchone()[0]

                    album_id = None
                    if album_title is None:
                        cur.execute(
                            "SELECT id FROM albums WHERE artist_id = ? AND title IS NULL",
                            (artist_id,),
                        )
                        row = cur.fetchone()
                        if row:
                            album_id = row[0]
                        else:
                            cur.execute(
                                "INSERT INTO albums(artist_id, title, year) VALUES (?, NULL, ?)",
                                (artist_id, year),
                            )
                            album_id = cur.lastrowid
                    else:
                        cur.execute(
                            "INSERT OR IGNORE INTO albums(artist_id, title, year) VALUES (?, ?, ?)",
                            (artist_id, album_title, year),
                        )
                        cur.execute(
                            "SELECT id FROM albums WHERE artist_id = ? AND title = ?",
                            (artist_id, album_title),
                        )
                        album_id = cur.fetchone()[0]

                    if not incremental:
                        cur.execute("DELETE FROM track_genres WHERE track_id IN (SELECT id FROM tracks WHERE path = ?)", (path,))
                        cur.execute("DELETE FROM tracks WHERE path = ?", (path,))

                    cur.execute(
                        """
                        INSERT INTO tracks(album_id, title, year, duration, path)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (album_id, title, year, duration, path),
                    )

                    cur.execute("SELECT id FROM tracks WHERE path = ?", (path,))
                    track_id = cur.fetchone()[0]

                    apply_genres(track_id)

                    ingested += 1
                except Exception as e:
                    logger.warning(
                        "[DB] Ingest error for jellyfin_id=%s title=%s artist=%s: %s",
                        track.get("jellyfin_id") or track.get("jellyfin_item_id"),
                        track.get("song") or track.get("name"),
                        track.get("artist"),
                        e,
                    )
                    errors += 1

            conn.commit()

        self._cached_query.cache_clear()

        try:
            conn = self._ensure_connection()
            with self._lock:
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    ("last_ingest_time", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                )
                conn.commit()
        except Exception:
            pass

        return {"ingested": ingested, "skipped": skipped, "errors": errors}

    def record_ingest_anomaly(
        self,
        *,
        jellyfin_id: str,
        issue: str,
        raw_name: Optional[str] = None,
        path: Optional[str] = None,
    ) -> None:
        if not jellyfin_id:
            return
        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO ingest_anomalies(jellyfin_id, issue, raw_name, path) VALUES (?, ?, ?, ?)",
                (jellyfin_id, issue, raw_name, path),
            )
            conn.commit()

    def query_tracks(
        self,
        *,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        genre: Optional[str] = None,
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
        limit: int = 50,
        intent: Optional[str] = None,
    ) -> List[Dict]:
        conditions = []
        params: List = []

        if title:
            conditions.append("LOWER(t.title) = LOWER(?)")
            params.append(title)
        if artist:
            conditions.append("LOWER(a.name) = LOWER(?)")
            params.append(artist)
        if genre:
            conditions.append("LOWER(g.name) = LOWER(?)")
            params.append(genre)
        if year_start is not None:
            conditions.append("t.year >= ?")
            params.append(year_start)
        if year_end is not None:
            conditions.append("t.year <= ?")
            params.append(year_end)

        where_clause = " AND ".join(conditions)
        if where_clause:
            where_clause = "WHERE " + where_clause

        exact_title_param = title or ""
        year_match_clause = "0"
        if year_start is not None and year_end is not None:
            year_match_clause = "CASE WHEN t.year BETWEEN ? AND ? THEN 1 ELSE 0 END"
            params.extend([year_start, year_end])

        sql = f"""
            SELECT
                t.id,
                t.title,
                t.year,
                t.duration,
                t.path,
                a.name AS artist,
                COALESCE(a.sovereignty_rank, 0) AS sovereignty_rank,
                al.title AS album,
                GROUP_CONCAT(g.name) AS genres,
                CASE WHEN LOWER(t.title) = LOWER(?) THEN 1 ELSE 0 END AS exact_title_match,
                {year_match_clause} AS era_match
            FROM tracks t
            LEFT JOIN albums al ON al.id = t.album_id
            LEFT JOIN artists a ON a.id = al.artist_id
            LEFT JOIN track_genres tg ON tg.track_id = t.id
            LEFT JOIN genres g ON g.id = tg.genre_id
            {where_clause}
            GROUP BY t.id
            ORDER BY
                exact_title_match DESC,
                COALESCE(a.sovereignty_rank, 0) DESC,
                COALESCE(t.year, 9999) ASC,
                t.title ASC
            LIMIT ?
        """

        params = [exact_title_param] + params + [limit]
        normalized_intent = (intent or "").strip().lower()
        start = time.perf_counter()
        results = self._cached_query(title, artist, genre, year_start, year_end, limit, normalized_intent)
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.info("[DB] intent=\"%s\"", intent or "")
        logger.info("[DB] sql=\"%s\"", " ".join(sql.split()))
        logger.info("[DB] results=%s latency=%sms", len(results), latency_ms)
        return list(results)

    def query_tracks_soft_title(
        self,
        title: str,
        *,
        limit: int = 200,
        intent: Optional[str] = None,
    ) -> List[Dict]:
        normalized = normalize_title(title)
        if not normalized:
            return []
        tokens = normalized.split()
        if not tokens:
            return []

        seed_token = tokens[0]
        sql = """
            SELECT
                t.id,
                t.title,
                t.year,
                t.duration,
                t.path,
                a.name AS artist,
                COALESCE(a.sovereignty_rank, 0) AS sovereignty_rank,
                al.title AS album,
                GROUP_CONCAT(g.name) AS genres
            FROM tracks t
            LEFT JOIN albums al ON al.id = t.album_id
            LEFT JOIN artists a ON a.id = al.artist_id
            LEFT JOIN track_genres tg ON tg.track_id = t.id
            LEFT JOIN genres g ON g.id = tg.genre_id
            WHERE LOWER(t.title) LIKE ?
            GROUP BY t.id
            ORDER BY
                COALESCE(a.sovereignty_rank, 0) DESC,
                COALESCE(t.year, 9999) ASC,
                t.title ASC
            LIMIT ?
        """

        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            cur.execute(sql, (f"%{seed_token}%", limit))
            rows = cur.fetchall()

        results = []
        seen_ids = set()
        for row in rows:
            if normalize_title(row[1]) != normalized:
                continue
            results.append(
                {
                    "id": row[0],
                    "song": row[1],
                    "year": row[2],
                    "duration": row[3],
                    "path": row[4],
                    "artist": row[5],
                    "sovereignty_rank": row[6],
                    "album": row[7],
                    "genre": row[8].split(",") if row[8] else [],
                }
            )
            seen_ids.add(row[0])

        if not results:
            prefix_sql = """
                SELECT
                    t.id,
                    t.title,
                    t.year,
                    t.duration,
                    t.path,
                    a.name AS artist,
                    COALESCE(a.sovereignty_rank, 0) AS sovereignty_rank,
                    al.title AS album,
                    GROUP_CONCAT(g.name) AS genres
                FROM tracks t
                LEFT JOIN albums al ON al.id = t.album_id
                LEFT JOIN artists a ON a.id = al.artist_id
                LEFT JOIN track_genres tg ON tg.track_id = t.id
                LEFT JOIN genres g ON g.id = tg.genre_id
                WHERE LOWER(t.title) LIKE LOWER(? || '%')
                GROUP BY t.id
                ORDER BY
                    COALESCE(a.sovereignty_rank, 0) DESC,
                    COALESCE(t.year, 9999) ASC,
                    t.title ASC
                LIMIT ?
            """
            with self._lock:
                cur = conn.cursor()
                cur.execute(prefix_sql, (normalized, limit))
                prefix_rows = cur.fetchall()
            for row in prefix_rows:
                if row[0] in seen_ids:
                    continue
                normalized_row = normalize_title(row[1])
                if not normalized_row or not normalized_row.startswith(normalized):
                    continue
                results.append(
                    {
                        "id": row[0],
                        "song": row[1],
                        "year": row[2],
                        "duration": row[3],
                        "path": row[4],
                        "artist": row[5],
                        "sovereignty_rank": row[6],
                        "album": row[7],
                        "genre": row[8].split(",") if row[8] else [],
                    }
                )
        if intent is not None:
            logger.info("[DB] soft_title intent=\"%s\" results=%s", intent, len(results))
        return results

    def query_tracks_artist_like(
        self,
        artist: str,
        *,
        limit: int = 200,
        intent: Optional[str] = None,
    ) -> List[Dict]:
        if not artist:
            return []
        sql = """
            SELECT
                t.id,
                t.title,
                t.year,
                t.duration,
                t.path,
                a.name AS artist,
                COALESCE(a.sovereignty_rank, 0) AS sovereignty_rank,
                al.title AS album,
                GROUP_CONCAT(g.name) AS genres
            FROM tracks t
            JOIN albums al ON al.id = t.album_id
            JOIN artists a ON a.id = al.artist_id
            LEFT JOIN track_genres tg ON tg.track_id = t.id
            LEFT JOIN genres g ON g.id = tg.genre_id
            WHERE LOWER(a.name) LIKE LOWER(?)
            GROUP BY t.id
            ORDER BY
                COALESCE(a.sovereignty_rank, 0) DESC,
                COALESCE(t.year, 9999) ASC,
                t.title ASC
            LIMIT ?
        """

        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            cur.execute(sql, (f"%{artist}%", limit))
            rows = cur.fetchall()

        results = []
        for row in rows:
            results.append(
                {
                    "id": row[0],
                    "song": row[1],
                    "year": row[2],
                    "duration": row[3],
                    "path": row[4],
                    "artist": row[5],
                    "sovereignty_rank": row[6],
                    "album": row[7],
                    "genre": row[8].split(",") if row[8] else [],
                }
            )
        if intent is not None:
            logger.info("[DB] artist_like intent=\"%s\" results=%s", intent, len(results))
        return results

    def _query_tracks_uncached(
        self,
        title: Optional[str],
        artist: Optional[str],
        genre: Optional[str],
        year_start: Optional[int],
        year_end: Optional[int],
        limit: int,
        _intent_key: str,
    ) -> tuple:
        conditions = []
        params: List = []

        if title:
            conditions.append("LOWER(t.title) = LOWER(?)")
            params.append(title)
        if artist:
            conditions.append("LOWER(a.name) = LOWER(?)")
            params.append(artist)
        if genre:
            conditions.append("LOWER(g.name) = LOWER(?)")
            params.append(genre)
        if year_start is not None:
            conditions.append("t.year >= ?")
            params.append(year_start)
        if year_end is not None:
            conditions.append("t.year <= ?")
            params.append(year_end)

        where_clause = " AND ".join(conditions)
        if where_clause:
            where_clause = "WHERE " + where_clause

        exact_title_param = title or ""
        year_match_clause = "0"
        if year_start is not None and year_end is not None:
            year_match_clause = "CASE WHEN t.year BETWEEN ? AND ? THEN 1 ELSE 0 END"
            params.extend([year_start, year_end])

        sql = f"""
            SELECT
                t.id,
                t.title,
                t.year,
                t.duration,
                t.path,
                a.name AS artist,
                COALESCE(a.sovereignty_rank, 0) AS sovereignty_rank,
                al.title AS album,
                GROUP_CONCAT(g.name) AS genres
            FROM tracks t
            LEFT JOIN albums al ON al.id = t.album_id
            LEFT JOIN artists a ON a.id = al.artist_id
            LEFT JOIN track_genres tg ON tg.track_id = t.id
            LEFT JOIN genres g ON g.id = tg.genre_id
            {where_clause}
            GROUP BY t.id
            ORDER BY
                CASE WHEN LOWER(t.title) = LOWER(?) THEN 1 ELSE 0 END DESC,
                COALESCE(a.sovereignty_rank, 0) DESC,
                COALESCE(t.year, 9999) ASC,
                t.title ASC
            LIMIT ?
        """

        params = [exact_title_param] + params + [limit]
        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()

        results = []
        for row in rows:
            results.append(
                {
                    "id": row[0],
                    "song": row[1],
                    "year": row[2],
                    "duration": row[3],
                    "path": row[4],
                    "artist": row[5],
                    "sovereignty_rank": row[6],
                    "album": row[7],
                    "genre": row[8].split(",") if row[8] else [],
                }
            )
        return tuple(results)

    def random_track(self) -> Optional[Dict]:
        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    t.id,
                    t.title,
                    t.year,
                    t.duration,
                    t.path,
                    a.name AS artist,
                    al.title AS album,
                FROM tracks t
                JOIN albums al ON al.id = t.album_id
                JOIN artists a ON a.id = al.artist_id
                ORDER BY RANDOM()
                LIMIT 1
                """
            )
            row = cur.fetchone()

        if not row:
            return None

        return {
            "id": row[0],
            "song": row[1],
            "year": row[2],
            "duration": row[3],
            "path": row[4],
            "artist": row[5],
            "album": row[6],
            "genre": [],
        }

    def count_tracks(self) -> int:
        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM tracks")
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def get_adjacent_genres(self, genre: str) -> List[str]:
        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT g2.name
                FROM genres g1
                JOIN genre_adjacency ga ON ga.genre_id = g1.id
                JOIN genres g2 ON g2.id = ga.adjacent_genre_id
                WHERE LOWER(g1.name) = LOWER(?)
                ORDER BY g2.name ASC
                """,
                (genre,),
            )
            rows = cur.fetchall()
        return [row[0] for row in rows]

    def optimize(self, vacuum: bool = False) -> None:
        conn = self._ensure_connection()
        with self._lock:
            cur = conn.cursor()
            cur.execute("ANALYZE")
            if vacuum:
                cur.execute("VACUUM")
            conn.commit()
