# ARGO v1.8.0 Release Notes

Date: 2026-05-10
Milestone: PostgreSQL Memory Backend

## Summary

v1.8.0 makes ARGO's durable memory backend swappable. SQLite remains the default local backend, while PostgreSQL can now be enabled for stronger long-term memory experiments.

## Added

- Optional PostgreSQL memory backend behind `core.memory_store`
- Backend selection through `memory.backend` or `ARGO_MEMORY_BACKEND`
- PostgreSQL DSN support through config or `ARGO_POSTGRES_DSN`
- Durable `conversation_turns` table for future long-term recall
- Migration script: `scripts/migrate_memory_to_postgres.py`
- Tests for backend selection and SQLite conversation-turn search

## Kept Safe

- SQLite remains the default
- Existing memory callers keep using `get_memory_store()`
- Migration is additive and does not delete SQLite data
- `ArgoBrain` working state remains SQLite for now

## Next

- Store completed assistant turns into `conversation_turns`
- Add pgvector embeddings for semantic recall
- Surface memory backend status in the frontend
