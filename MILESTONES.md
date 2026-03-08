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

## ✅ Milestone: Self-Diagnostics + Security Hardening (v1.6.25 — 2026-03-07)

**Goal:** Enable ARGO to detect its own component failures, propose recovery actions with user approval, and harden security for home-network use.

### Completed
- [✔] Self-diagnostics module (`core/self_diagnostics.py`) — Phase 1 detect & explain
- [✔] Assisted recovery system — Phase 2 propose & execute with user permission
- [✔] Intent detection for diagnostics phrases (24 natural-language triggers)
- [✔] Pipeline handler for spoken diagnostics report
- [✔] WebSocket diagnostics and recovery message types
- [✔] Frontend diagnostics panel (v2.8) with recovery prompts
- [✔] Network binding hardened to 127.0.0.1 (WebSocket, HTTP, Vite)
- [✔] LiveKit secrets moved to environment variables
- [✔] SQL injection prevention in check_db.py
- [✔] Porcupine key and ARGO_SLIM_CONTEXT removed from repo
- [✔] STT warmup crash fix (threaded context)
- [✔] IRQ profiling hang fix
- [✔] Requirements pinned to exact versions
- [✔] Security audit documented (SECURITY_AUDIT.md)

---

## Upcoming

[ ] Mode Discipline
[ ] Status / Debug Introspection
[ ] Earned System Controls
