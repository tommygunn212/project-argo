# PostgreSQL Memory Backend

Status: v1.8.0 optional backend.

ARGO still defaults to SQLite. PostgreSQL is available when you want a stronger long-term memory store, concurrent access, and a path toward pgvector semantic recall.

## Backend Selection

Use config:

```json
{
  "memory": {
    "backend": "postgres",
    "sqlite_path": "data/memory.db",
    "postgres_dsn": "postgresql://argo:argo@localhost:5432/argo"
  }
}
```

Or environment:

```powershell
$env:ARGO_MEMORY_BACKEND="postgres"
$env:ARGO_POSTGRES_DSN="postgresql://argo:argo@localhost:5432/argo"
```

If `ARGO_MEMORY_BACKEND` is unset, ARGO uses SQLite.

## What Moves To PostgreSQL

The v1.8.0 backend supports:

- explicit durable memory records (`FACT`, `PROJECT`, `PREFERENCE`)
- conversation-turn storage for completed LLM replies
- durable turn recall during memory context assembly
- full-text indexing over conversation turns in PostgreSQL

The current `ArgoBrain` working-state database still uses SQLite. That keeps this milestone reversible while the memory backend boundary settles.

## Migration

```powershell
python scripts/migrate_memory_to_postgres.py --dsn $env:ARGO_POSTGRES_DSN
```

The migration copies records from `data/memory.db` and skips exact duplicates. It does not delete the SQLite source.

Dry run:

```powershell
python scripts/migrate_memory_to_postgres.py --dsn $env:ARGO_POSTGRES_DSN --dry-run
```

## Why This Shape

The goal is not just "swap SQLite for Postgres." The useful architecture is a stable memory API:

```text
conversation turn
-> retrieve relevant memory
-> generate response
-> store durable facts / turns
```

SQLite keeps the local assistant simple. PostgreSQL gives ARGO a better base for bigger memory, multi-client use, full-text search, and pgvector later.

## Next Step

The next milestone should add embeddings and pgvector similarity search behind the same `MemoryStore` boundary.
