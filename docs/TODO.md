# TODO / Next Steps (v1.9.1)

Short list of deferred or optional work items. The v1.9.1 voice reliability batch, backend provider router, Phone Vision upload path, and local Cortana animation are implemented. No refactors are implied by this list.

## Immediate validation — Voice reliability
- [ ] Run a real microphone turn on both classic and LiveKit paths with current live-path instrumentation.
- [ ] Verify interruption reaches the selected physical output device and diagnose the observed OpenAI TTS output-underflow warning.
- [ ] Measure endpointing, network/SDK events, first device write, and audible onset separately; do not infer end-to-end latency from a TTS-only run.
- [ ] Resolve audio ownership for transition sound cues and evaluate endpointing/AEC changes with fresh reproducible tests.

## Current product follow-through
- [ ] Add `/v2` controls for provider enablement, model selection, fallback order, and an explicit opt-in multi-model compare mode.
- [ ] Connect ARGO's UI/voice flow to the auditable coding-request record, then add agent dispatch only after a callable agent surface is verified.
- [ ] Add optional manual live-camera frames for Phone Vision without continuous private camera streaming.
- [ ] Enroll and validate Speaker-ID profiles before using speaker identity as a convenience signal; retain confirmation for sensitive actions.

## Phase 2 — API Readiness (Optional)
- [ ] Create requirements-api.txt
- [ ] Install fastapi + uvicorn
- [ ] Run test_app.py
- [ ] Fix API-layer issues only (no core changes)

## Phase 2B — Long-Term Memory Backend
- [x] Add optional PostgreSQL memory backend with SQLite fallback
- [x] Add migration script for existing SQLite memory records
- [x] Store completed assistant turns into `conversation_turns`
- [ ] Add pgvector embeddings for semantic recall
- [ ] Expose memory backend health in the UI

## Phase 3 — Test Hygiene (Low Risk)
- [ ] Move deprecated tests into tests/deprecated/
- [ ] Add legacy comments to historical tests
- [ ] Update docs to explain why v1 tests remain

## Phase 4 — Intent & Music Policy Alignment
- [ ] Align intent taxonomy with v2 expectations
- [ ] Decide behavior for “play music” vs generic command
- [ ] Document empty-index music behavior (policy note)

## Phase 5 — Personality & Voice
- [ ] Define personality injection post-LLM, pre-output
- [ ] Keep deterministic, optional, non-blocking

## Phase 6 — Explanation Modes
- [ ] Add explanation tiers (general / technical / programmer)
- [ ] Update docs + demo scripts
