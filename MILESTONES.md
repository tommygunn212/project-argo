# ARGO Milestones

---

## ✅ Milestone: Deterministic Core Stabilization (v1.6.1 — 2026-02-02)

**Goal:** Ensure canonical / deterministic commands bypass STT confidence gates and never fall back to LLM speculation.

### Completed
- [✔] Canonical commands bypass STT confidence gate in coordinator.py
- [✔] Unresolved noun phrase detection triggers clarification, not LLM fallback
- [✔] VAD_END minimum voiced speech threshold lowered to 240ms
- [✔] Type safety: All pipeline.py method stubs and type annotations resolved
- [✔] Test harness safety: import-time sys.exit() removed from 4 test files
- [✔] bare except: clauses replaced with logged exceptions

### Known Test Debt
- 12 pre-existing test failures tracked in TEST_DEBT.md

---

## Previous Milestones

[✔] Memory Semantics Locked
[✔] STT Determinism Achieved
[✔] Chaos Stress Test Passing

---

## Upcoming

[ ] Mode Discipline
[ ] Status / Debug Introspection
[ ] Earned System Controls
