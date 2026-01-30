# DATABASE.md

## ARGO Neural Network: Database and SQL Integration

This document describes all current and planned database schemas, SQL query patterns, and data flows for ARGO, the neural network command diagnostic system.

### Current State (Jan 2026)
- No persistent SQL database is currently in use for core ARGO operations.
- All memory and session data are stored in local JSON files for deterministic recall and auditability.

### Planned SQL Features
- Integration of a local SQL database for structured data storage and advanced queries.
- Canonical schema for session logs, user preferences, and feature usage tracking.
- Deterministic query patterns for all database operations (no generative synthesis).
- All SQL queries and schema changes will be documented here for deterministic self-knowledge.

### Example Canonical SQL Query
```sql
SELECT * FROM session_logs WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10;
```

---

This file is canonical. All ARGO self-knowledge and SQL/database queries should be answered deterministically from this document.
