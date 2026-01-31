import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "argo_knowledge.db"

INCLUDE_EXT = {".md", ".py", ".txt", ".json", ".yml", ".yaml", ".toml"}
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "archive",
    "backups",
    "logs",
    "temp",
    "temp_piper",
    "runtime",
    "whisper.cpp",
}

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200


@dataclass
class DocChunk:
    path: str
    start_line: int
    end_line: int
    text: str


def _iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() in INCLUDE_EXT:
                yield path


def _split_lines(text: str) -> List[str]:
    return text.splitlines()


def _chunk_text(lines: List[str]) -> Iterable[Tuple[int, int, str]]:
    buf: List[str] = []
    start = 0
    idx = 0
    while idx < len(lines):
        if not buf:
            start = idx
        buf.append(lines[idx])
        current = "\n".join(buf)
        if len(current) >= CHUNK_SIZE:
            end = idx
            yield start + 1, end + 1, current
            overlap_start = max(start, end - _line_offset_for_overlap(lines, end))
            buf = lines[overlap_start : end + 1]
            start = overlap_start
        idx += 1
    if buf:
        yield start + 1, len(lines), "\n".join(buf)


def _line_offset_for_overlap(lines: List[str], end_idx: int) -> int:
    length = 0
    count = 0
    idx = end_idx
    while idx >= 0 and length < CHUNK_OVERLAP:
        length += len(lines[idx]) + 1
        count += 1
        idx -= 1
    return count


def _normalize_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned


def _connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            text TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
        USING fts5(text, content='chunks', content_rowid='id')
        """
    )
    return conn


def rebuild_index() -> None:
    conn = _connect_db(DB_PATH)
    conn.execute("DELETE FROM chunks")
    conn.execute("DELETE FROM chunks_fts")
    conn.commit()

    batch = []
    for path in _iter_files(ROOT):
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        lines = _split_lines(content)
        for start_line, end_line, chunk in _chunk_text(lines):
            text = _normalize_text(chunk)
            if not text:
                continue
            batch.append((str(path.relative_to(ROOT)), start_line, end_line, text))
            if len(batch) >= 500:
                _flush(conn, batch)
                batch.clear()

    if batch:
        _flush(conn, batch)
    conn.commit()
    conn.close()


def _flush(conn: sqlite3.Connection, batch: List[Tuple[str, int, int, str]]) -> None:
    conn.executemany(
        "INSERT INTO chunks(path, start_line, end_line, text) VALUES(?, ?, ?, ?)",
        batch,
    )
    conn.executemany(
        "INSERT INTO chunks_fts(rowid, text) VALUES(last_insert_rowid(), ?)",
        [(b[3],) for b in batch],
    )


def query_index(query: str, limit: int = 8) -> List[DocChunk]:
    conn = _connect_db(DB_PATH)
    cursor = conn.execute(
        """
        SELECT c.path, c.start_line, c.end_line, c.text
        FROM chunks_fts f
        JOIN chunks c ON c.id = f.rowid
        WHERE chunks_fts MATCH ?
        ORDER BY bm25(chunks_fts)
        LIMIT ?
        """,
        (query, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    return [DocChunk(path, start, end, text) for path, start, end, text in rows]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="ARGO local RAG (SQLite FTS)")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the index")
    parser.add_argument("--query", type=str, help="Query text")
    parser.add_argument("--limit", type=int, default=8, help="Result limit")

    args = parser.parse_args()

    if args.rebuild:
        rebuild_index()
        print(f"Index rebuilt at {DB_PATH}")
        return

    if args.query:
        results = query_index(args.query, args.limit)
        for i, chunk in enumerate(results, 1):
            print(f"[{i}] {chunk.path}:{chunk.start_line}-{chunk.end_line}")
            print(chunk.text)
            print()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
