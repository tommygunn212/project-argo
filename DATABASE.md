# DATABASE.md

## ARGO Database and Memory Backend

This document describes ARGO's durable database usage as of v1.8.0.

### Current State (May 2026)

ARGO uses SQLite by default and can opt into PostgreSQL for durable memory.

- Default backend: `sqlite`
- Default file: `data/memory.db`
- Optional backend: `postgres`
- Selector: `memory.backend` in `config.json`, or `ARGO_MEMORY_BACKEND`
- PostgreSQL DSN: `memory.postgres_dsn`, `ARGO_POSTGRES_DSN`, or `ARGO_MEMORY_POSTGRES_DSN`

SQLite remains the local-first safe default. PostgreSQL is for stronger long-term memory experiments, concurrent access, and future semantic/vector recall.

### Durable Memory Schema

Both SQLite and PostgreSQL expose the same application API through `core.memory_store`.

```sql
memory(
  id,
  type,
  namespace,
  key,
  value,
  source,
  timestamp
)
```

Allowed durable memory types:

- `FACT`
- `PROJECT`
- `PREFERENCE`

`EPHEMERAL` memory is intentionally not written to durable storage.

### Conversation Turn Schema

v1.8.0 adds a durable table for long-term conversation recall.

```sql
conversation_turns(
  id,
  user_text,
  assistant_text,
  source,
  intent,
  metadata,
  timestamp
)
```

The table is available in both backends. PostgreSQL creates a full-text index over user and assistant text.
Completed LLM turns are stored through this table. Matching turns are included in future memory context when relevant.

### Backend Selection

```json
{
  "memory": {
    "backend": "sqlite",
    "sqlite_path": "data/memory.db",
    "postgres_dsn": ""
  }
}
```

Environment variables override config:

```powershell
$env:ARGO_MEMORY_BACKEND="postgres"
$env:ARGO_POSTGRES_DSN="postgresql://argo:argo@localhost:5432/argo"
```

### Migration

Copy existing SQLite memory records into PostgreSQL:

```powershell
python scripts/migrate_memory_to_postgres.py --dsn $env:ARGO_POSTGRES_DSN
```

The migration is additive. It skips exact duplicate `type + namespace + key + value` records and does not delete SQLite data.

### Planned SQL Features

- pgvector-backed embedding search for semantic memory recall
- Hybrid full-text + vector search for conversation turns
- Background memory extraction from complete turns
- Admin tools for memory inspection, export, and deletion

---

This file is canonical. ARGO database and memory backend questions should be answered deterministically from this document.
