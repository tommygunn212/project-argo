# CLAUDE.md

Read [AGENTS.md](./AGENTS.md) first. It is the map of this repo and it exists
because agents keep rebuilding things ARGO already has.

Two rules that override default behaviour:

1. **Commit atomically.** Every time you write something, commit it immediately
   rather than batching changes. Standing instruction from Tommy.
2. **Verify from disk, never from the write.** File syncs into this repo have
   silently written stale bytes while reporting success. Read the file back and
   assert on markers after every patch.

For how to work here without burning context, see
[docs/WORKING-WITH-AGENTS.md](./docs/WORKING-WITH-AGENTS.md).
