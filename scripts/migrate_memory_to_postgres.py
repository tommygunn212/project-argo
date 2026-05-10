"""Copy ARGO SQLite memory records into the PostgreSQL memory backend.

Usage:
    python scripts/migrate_memory_to_postgres.py --dsn postgresql://argo:argo@localhost:5432/argo

The migration is additive and idempotent for matching type/namespace/key/value
records. It does not delete SQLite data.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.memory_store import MemoryStore, PostgresMemoryStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate ARGO memory.db records to PostgreSQL.")
    parser.add_argument("--sqlite", default="data/memory.db", help="Path to SQLite memory database.")
    parser.add_argument(
        "--dsn",
        default=os.getenv("ARGO_POSTGRES_DSN") or os.getenv("ARGO_MEMORY_POSTGRES_DSN"),
        help="PostgreSQL DSN. Defaults to ARGO_POSTGRES_DSN.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be copied without writing.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.dsn:
        print("Missing PostgreSQL DSN. Pass --dsn or set ARGO_POSTGRES_DSN.")
        return 2

    source = MemoryStore(Path(args.sqlite))
    destination = PostgresMemoryStore(args.dsn)

    existing = {
        (record.type, record.namespace, record.key.lower(), record.value)
        for record in destination.list_memory()
    }
    copied = 0
    skipped = 0
    records = list(reversed(source.list_memory()))

    for record in records:
        fingerprint = (record.type, record.namespace, record.key.lower(), record.value)
        if fingerprint in existing:
            skipped += 1
            continue
        copied += 1
        if not args.dry_run:
            destination.add_memory(
                record.type,
                record.key,
                record.value,
                source=f"sqlite_migration:{record.source}",
                namespace=record.namespace,
            )

    mode = "would copy" if args.dry_run else "copied"
    print(f"Memory migration complete: {mode}={copied}, skipped={skipped}, source={args.sqlite}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
