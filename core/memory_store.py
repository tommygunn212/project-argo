"""
SQLite-backed durable memory for ARGO.

Contract:
- Memory is explicit only (no auto-learning).
- Only three types exist: FACT, PROJECT, EPHEMERAL.
- EPHEMERAL never touches disk.
- SQLite is the source of truth for durable memory.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
import sqlite3

DB_PATH = Path("data") / "memory.db"


@dataclass
class MemoryRecord:
    id: int
    type: str
    namespace: Optional[str]
    key: str
    value: str
    source: str
    timestamp: str


class MemoryStore:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
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
        if mem_type not in {"FACT", "PROJECT"}:
            raise ValueError("mem_type must be FACT or PROJECT")
        ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn = self._connect()
        cur = conn.execute(
            "INSERT INTO memory(type, namespace, key, value, source, timestamp) VALUES(?, ?, ?, ?, ?, ?)",
            (mem_type, namespace, key, value, source, ts),
        )
        conn.commit()
        row_id = int(cur.lastrowid)
        conn.close()
        return row_id

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
        cur = conn.execute(query, params)
        conn.commit()
        count = int(cur.rowcount)
        conn.close()
        return count

    def clear_project(self, namespace: str) -> int:
        conn = self._connect()
        cur = conn.execute("DELETE FROM memory WHERE type = 'PROJECT' AND namespace = ?", (namespace,))
        conn.commit()
        count = int(cur.rowcount)
        conn.close()
        return count

    def clear_all(self) -> int:
        conn = self._connect()
        cur = conn.execute("DELETE FROM memory")
        conn.commit()
        count = int(cur.rowcount)
        conn.close()
        return count

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


_memory_store_instance: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    global _memory_store_instance
    if _memory_store_instance is None:
        _memory_store_instance = MemoryStore()
    return _memory_store_instance
