"""Durable memory backends for ARGO.

Contract:
- Memory is explicit only unless a caller intentionally stores a conversation turn.
- Only FACT, PROJECT, and PREFERENCE touch durable storage.
- SQLite remains the local default.
- PostgreSQL can be selected with config/env without changing pipeline callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
import json
import os
import re
import sqlite3

DB_PATH = Path("data") / "memory.db"
VALID_MEMORY_TYPES = {"FACT", "PROJECT", "PREFERENCE"}


@dataclass
class MemoryRecord:
    id: int
    type: str
    namespace: Optional[str]
    key: str
    value: str
    source: str
    timestamp: str


@dataclass
class ConversationTurnRecord:
    id: int
    user_text: str
    assistant_text: str
    source: str
    intent: Optional[str]
    metadata: dict
    timestamp: str


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _format_timestamp(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        text = value.isoformat(timespec="seconds")
        return text.replace("+00:00", "Z")
    return str(value)


def _validate_memory_type(mem_type: str) -> None:
    if mem_type not in VALID_MEMORY_TYPES:
        raise ValueError("mem_type must be FACT, PROJECT, or PREFERENCE")


def _query_terms(query: str) -> list[str]:
    return [term for term in re.findall(r"[a-z0-9]{2,}", (query or "").lower())[:8]]


class MemoryStore:
    """SQLite-backed durable memory store."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @property
    def backend_name(self) -> str:
        return "sqlite"

    def _connect(self) -> sqlite3.Connection:
        # Short timeout ensures locked DBs fail fast and can be handled gracefully upstream.
        conn = sqlite3.connect(self.db_path, timeout=0.2)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                namespace TEXT NULL,
                key TEXT NOT NULL COLLATE NOCASE,
                value TEXT NOT NULL,
                source TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_key ON memory(key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_type ON memory(type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_namespace ON memory(namespace)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_text TEXT NOT NULL,
                assistant_text TEXT NOT NULL,
                source TEXT NOT NULL,
                intent TEXT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversation_turns_timestamp ON conversation_turns(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversation_turns_intent ON conversation_turns(intent)")
        conn.commit()
        conn.close()

    def add_memory(
        self,
        mem_type: str,
        key: str,
        value: str,
        source: str,
        namespace: Optional[str] = None,
    ) -> int:
        # Guard: EPHEMERAL must never be written to disk.
        _validate_memory_type(mem_type)
        ts = _utc_timestamp()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "INSERT INTO memory(type, namespace, key, value, source, timestamp) VALUES(?, ?, ?, ?, ?, ?)",
                (mem_type, namespace, key, value, source, ts),
            )
            conn.commit()
            return int(cur.lastrowid)
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_memory(
        self,
        mem_type: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[MemoryRecord]:
        conn = self._connect()
        query = "SELECT id, type, namespace, key, value, source, timestamp FROM memory"
        where = []
        params: List[str] = []
        if mem_type:
            where.append("type = ?")
            params.append(mem_type)
        if namespace is not None:
            where.append("namespace = ?")
            params.append(namespace)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY id DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [MemoryRecord(*row) for row in rows]

    def delete_memory(
        self,
        key: str,
        mem_type: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> int:
        conn = self._connect()
        query = "DELETE FROM memory WHERE key = ?"
        params: List[str] = [key]
        if mem_type:
            query += " AND type = ?"
            params.append(mem_type)
        if namespace is not None:
            query += " AND namespace = ?"
            params.append(namespace)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(query, params)
            conn.commit()
            return int(cur.rowcount)
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_project(self, namespace: str) -> int:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("DELETE FROM memory WHERE type = 'PROJECT' AND namespace = ?", (namespace,))
            conn.commit()
            return int(cur.rowcount)
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_all(self) -> int:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("DELETE FROM memory")
            conn.commit()
            return int(cur.rowcount)
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_by_key(
        self,
        key: str,
        mem_type: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[MemoryRecord]:
        conn = self._connect()
        query = "SELECT id, type, namespace, key, value, source, timestamp FROM memory WHERE key = ?"
        params: List[str] = [key]
        if mem_type:
            query += " AND type = ?"
            params.append(mem_type)
        if namespace is not None:
            query += " AND namespace = ?"
            params.append(namespace)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [MemoryRecord(*row) for row in rows]

    def add_turn(
        self,
        user_text: str,
        assistant_text: str,
        source: str = "assistant",
        intent: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> int:
        if not user_text or not assistant_text:
            return -1
        ts = _utc_timestamp()
        metadata_text = json.dumps(metadata or {}, sort_keys=True)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                """
                INSERT INTO conversation_turns(user_text, assistant_text, source, intent, metadata, timestamp)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (user_text, assistant_text, source, intent, metadata_text, ts),
            )
            conn.commit()
            return int(cur.lastrowid)
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()

    def search_turns(self, query: str, limit: int = 5) -> List[ConversationTurnRecord]:
        limit = max(1, min(int(limit or 5), 20))
        conn = self._connect()
        terms = _query_terms(query)
        if terms:
            clauses = []
            params: list[Any] = []
            for term in terms:
                pattern = f"%{term}%"
                clauses.append("(lower(user_text) LIKE ? OR lower(assistant_text) LIKE ?)")
                params.extend([pattern, pattern])
            sql = (
                "SELECT id, user_text, assistant_text, source, intent, metadata, timestamp "
                "FROM conversation_turns WHERE "
                + " OR ".join(clauses)
                + " ORDER BY id DESC LIMIT ?"
            )
            params.append(limit)
        else:
            sql = (
                "SELECT id, user_text, assistant_text, source, intent, metadata, timestamp "
                "FROM conversation_turns ORDER BY id DESC LIMIT ?"
            )
            params = [limit]
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [
            ConversationTurnRecord(
                id=row[0],
                user_text=row[1],
                assistant_text=row[2],
                source=row[3],
                intent=row[4],
                metadata=json.loads(row[5] or "{}"),
                timestamp=row[6],
            )
            for row in rows
        ]


class PostgresMemoryStore:
    """PostgreSQL-backed durable memory store.

    This intentionally mirrors MemoryStore so callers can swap backends through
    get_memory_store() without knowing which database is underneath.
    """

    def __init__(self, dsn: str, connect_timeout: int = 3):
        if not dsn:
            raise ValueError("PostgreSQL memory backend requires a DSN")
        self.dsn = dsn
        self.connect_timeout = connect_timeout
        self._init_db()

    @property
    def backend_name(self) -> str:
        return "postgres"

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL memory backend requires psycopg. Install requirements.txt first."
            ) from exc
        return psycopg.connect(self.dsn, connect_timeout=self.connect_timeout)

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory (
                        id BIGSERIAL PRIMARY KEY,
                        type TEXT NOT NULL CHECK (type IN ('FACT', 'PROJECT', 'PREFERENCE')),
                        namespace TEXT NULL,
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        source TEXT NOT NULL,
                        timestamp TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_key_lower ON memory (lower(key))")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_type ON memory(type)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_namespace ON memory(namespace)")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversation_turns (
                        id BIGSERIAL PRIMARY KEY,
                        user_text TEXT NOT NULL,
                        assistant_text TEXT NOT NULL,
                        source TEXT NOT NULL,
                        intent TEXT NULL,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        timestamp TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now())
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_conversation_turns_timestamp "
                    "ON conversation_turns(timestamp DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_conversation_turns_fts "
                    "ON conversation_turns USING GIN "
                    "(to_tsvector('english', coalesce(user_text, '') || ' ' || coalesce(assistant_text, '')))"
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def add_memory(
        self,
        mem_type: str,
        key: str,
        value: str,
        source: str,
        namespace: Optional[str] = None,
    ) -> int:
        _validate_memory_type(mem_type)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory(type, namespace, key, value, source)
                    VALUES(%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (mem_type, namespace, key, value, source),
                )
                row = cur.fetchone()
            conn.commit()
            return int(row[0])
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_memory(
        self,
        mem_type: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[MemoryRecord]:
        query = "SELECT id, type, namespace, key, value, source, timestamp FROM memory"
        where = []
        params: list[Any] = []
        if mem_type:
            where.append("type = %s")
            params.append(mem_type)
        if namespace is not None:
            where.append("namespace = %s")
            params.append(namespace)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY id DESC"
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
            return [MemoryRecord(row[0], row[1], row[2], row[3], row[4], row[5], _format_timestamp(row[6])) for row in rows]
        finally:
            conn.close()

    def delete_memory(
        self,
        key: str,
        mem_type: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> int:
        query = "DELETE FROM memory WHERE lower(key) = lower(%s)"
        params: list[Any] = [key]
        if mem_type:
            query += " AND type = %s"
            params.append(mem_type)
        if namespace is not None:
            query += " AND namespace = %s"
            params.append(namespace)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                count = int(cur.rowcount)
            conn.commit()
            return count
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_project(self, namespace: str) -> int:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM memory WHERE type = 'PROJECT' AND namespace = %s", (namespace,))
                count = int(cur.rowcount)
            conn.commit()
            return count
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_all(self) -> int:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM memory")
                count = int(cur.rowcount)
            conn.commit()
            return count
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_by_key(
        self,
        key: str,
        mem_type: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[MemoryRecord]:
        query = "SELECT id, type, namespace, key, value, source, timestamp FROM memory WHERE lower(key) = lower(%s)"
        params: list[Any] = [key]
        if mem_type:
            query += " AND type = %s"
            params.append(mem_type)
        if namespace is not None:
            query += " AND namespace = %s"
            params.append(namespace)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
            return [MemoryRecord(row[0], row[1], row[2], row[3], row[4], row[5], _format_timestamp(row[6])) for row in rows]
        finally:
            conn.close()

    def add_turn(
        self,
        user_text: str,
        assistant_text: str,
        source: str = "assistant",
        intent: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> int:
        if not user_text or not assistant_text:
            return -1
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversation_turns(user_text, assistant_text, source, intent, metadata)
                    VALUES(%s, %s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (user_text, assistant_text, source, intent, json.dumps(metadata or {}, sort_keys=True)),
                )
                row = cur.fetchone()
            conn.commit()
            return int(row[0])
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def search_turns(self, query: str, limit: int = 5) -> List[ConversationTurnRecord]:
        limit = max(1, min(int(limit or 5), 20))
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if _query_terms(query):
                    fts = "to_tsvector('english', coalesce(user_text, '') || ' ' || coalesce(assistant_text, ''))"
                    cur.execute(
                        f"""
                        SELECT id, user_text, assistant_text, source, intent, metadata, timestamp
                        FROM conversation_turns
                        WHERE {fts} @@ plainto_tsquery('english', %s)
                        ORDER BY ts_rank_cd({fts}, plainto_tsquery('english', %s)) DESC, id DESC
                        LIMIT %s
                        """,
                        (query, query, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, user_text, assistant_text, source, intent, metadata, timestamp
                        FROM conversation_turns
                        ORDER BY id DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                rows = cur.fetchall()
            return [
                ConversationTurnRecord(
                    id=row[0],
                    user_text=row[1],
                    assistant_text=row[2],
                    source=row[3],
                    intent=row[4],
                    metadata=dict(row[5] or {}),
                    timestamp=_format_timestamp(row[6]),
                )
                for row in rows
            ]
        finally:
            conn.close()


SQLiteMemoryStore = MemoryStore
_memory_store_instance: Optional[Any] = None


def _memory_backend_config() -> tuple[str, Path, Optional[str]]:
    backend = os.getenv("ARGO_MEMORY_BACKEND")
    sqlite_path = os.getenv("ARGO_MEMORY_SQLITE_PATH")
    postgres_dsn = os.getenv("ARGO_POSTGRES_DSN") or os.getenv("ARGO_MEMORY_POSTGRES_DSN")
    try:
        from core.config import get_config

        config = get_config()
        backend = backend or config.get("memory.backend")
        sqlite_path = sqlite_path or config.get("memory.sqlite_path")
        postgres_dsn = postgres_dsn or config.get("memory.postgres_dsn")
    except Exception:
        pass
    return (backend or "sqlite").strip().lower(), Path(sqlite_path or DB_PATH), postgres_dsn


def get_memory_store():
    global _memory_store_instance
    if _memory_store_instance is None:
        backend, sqlite_path, postgres_dsn = _memory_backend_config()
        if backend in {"postgres", "postgresql"}:
            _memory_store_instance = PostgresMemoryStore(postgres_dsn or "")
        elif backend == "sqlite":
            _memory_store_instance = MemoryStore(sqlite_path)
        else:
            raise ValueError(f"Unsupported memory backend: {backend}")
    return _memory_store_instance


def reset_memory_store_for_tests() -> None:
    global _memory_store_instance
    _memory_store_instance = None
