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

## ✅ Milestone: Frontend V2, Engine Upgrades & Barge-In Overhaul (v1.7.0 — 2026-03-08)

**Goal:** Deliver a production-quality control surface with runtime engine switching, real-time gate tuning, and reliable multi-engine barge-in handling.

### Completed
- [✔] Frontend V2 (`/v2`) — single-file cyberpunk UI with 6 tabs (Dashboard, Chat, Voice, Home, Tools, System)
- [✔] 14 gate tuning sliders in 3 groups (Audio Input, Speech Recognition, Response Output) with Reset to Defaults
- [✔] STT engine switching: OpenAI Cloud, Azure, Faster Whisper, OpenAI Whisper with context-sensitive model selectors
- [✔] TTS engine switching: OpenAI TTS (13 voices), Edge TTS, Azure Neural with context-sensitive voice/model selectors
- [✔] Active Pipeline display showing full STT→LLM→TTS combination
- [✔] STT upgraded to `gpt-4o-mini-transcribe` with prompt support
- [✔] TTS upgraded to `gpt-4o-mini-tts` with `instructions` parameter
- [✔] 3 new voices added: verse, marin, cedar (13 total)
- [✔] OpenAI TTS streaming rewritten (100ms initial buffer, 10ms polling for barge-in)
- [✔] Barge-in overhaul: `stop_tts()` handles both engines, suppression guards, buffer clearing, text barge-in cleanup
- [✔] Response quality: max_tokens 1024, max_sentences 10, system prompt rewritten, personas loosened
- [✔] STT engine manager reads configured model (no longer hardcoded)
- [✔] `/v2` HTTP route added to main.py
- [✔] Frontend v1 voice dropdown updated (13 OpenAI + 4 Edge voices)

---

## ✅ Milestone: PostgreSQL Memory Backend (v1.8.0 — 2026-05-10)

**Goal:** Make ARGO's durable memory backend swappable so SQLite stays the local default while PostgreSQL can power stronger long-term memory experiments.

### Completed
- [✔] `core.memory_store` now supports SQLite and PostgreSQL behind the same API
- [✔] Backend selection via `memory.backend`, `ARGO_MEMORY_BACKEND`, and DSN env vars
- [✔] PostgreSQL schema for explicit memory records
- [✔] Conversation-turn table added for long-term recall
- [✔] Completed LLM turns are stored through the durable backend
- [✔] Durable conversation-turn recall is included in memory context when relevant
- [✔] SQLite remains default and requires no setup
- [✔] Migration script copies existing SQLite memory records into PostgreSQL
- [✔] Memory tests cover backend selection and turn search
- [✔] Version registry normalized to v1.8.0

### Next
- [ ] Add embeddings and pgvector-backed semantic recall
- [ ] Add UI controls for memory backend health and migration status

## ✅ Milestone: LiveKit Realtime Voice + Cortana Companion Groundwork (v1.9.0 — 2026-06-03)

**Goal:** Make ARGO feel like a fast room assistant: smooth back-and-forth voice, clean interruption, a stable Cortana-style visual identity, and a clear path to speaker identity and mobile use.

### Completed
- [✔] LiveKit/OpenAI Realtime path is the preferred smooth conversation mode
- [✔] Frontend V2 quick action renamed to **Start Smooth Voice**
- [✔] Realtime interruption defaults tuned to `0.08s` min interruption and `0.22s` false-interruption timeout
- [✔] Cortana portrait asset is served locally as the dashboard/voice fallback visual
- [✔] Legacy Hedra Realtime avatar path is documented and disabled by default after provider shutdown
- [✔] Speechmatics, Silero, turn-detector, and noise-cancellation LiveKit plugins are included for the speaker-ID experiment path
- [✔] `/api/livekit-status` reports speaker identity readiness and avatar fallback state
- [✔] `/api/mobile-access` reports the same-network iPad/phone URL
- [✔] Behavior tuning UI exposes graded action-check loosen/tighten controls

### Next
- [ ] Add a dedicated Speechmatics speaker-ID sidecar that maps recurring voices to names
- [ ] Choose a current LiveKit avatar provider for real facial animation
- [ ] Add HTTPS or trusted local cert flow for easier mobile microphone permissions

---

## Upcoming

[ ] Mode Discipline
[ ] Status / Debug Introspection
[ ] Earned System Controls
[ ] pgvector semantic memory recall
