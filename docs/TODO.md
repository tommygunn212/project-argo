# TODO / Next Steps (v1.9.1)

Short list of deferred or optional work items. The v1.9.1 voice reliability batch, backend provider router, Phone Vision upload path, and local Cortana animation are implemented. No refactors are implied by this list.

## Immediate validation — Voice reliability
- [ ] Run a real microphone turn on both classic and LiveKit paths with current live-path instrumentation.
- [ ] Verify interruption reaches the selected physical output device and diagnose the observed OpenAI TTS output-underflow warning.
- [ ] Measure endpointing, network/SDK events, first device write, and audible onset separately; do not infer end-to-end latency from a TTS-only run.
- [ ] Resolve audio ownership for transition sound cues and evaluate endpointing/AEC changes with fresh reproducible tests.

## Repair automation — implemented boundary

- [x] Recognize ARGO-specific repair requests such as "your voice isn't working" and "diagnose and fix."
- [x] Require a visible, pending diagnostic proposal before an approved runtime repair can execute.
- [x] Re-run diagnostics after a successful runtime repair and show the observed result.
- [x] Create an auditable code-repair task and require an additional UI approval before local Codex dispatch.
- [x] Add process-status polling and a diff/review panel for completed Astra repair tasks.
- [x] Prepare changes in an independent checkout and apply only the reviewed, tested patch to an unchanged clean base.
- [x] Share runtime diagnosis, explicit spoken approval, and post-repair reporting between classic and Smooth Voice.
- [x] Replace the placeholder retry with a saved conversational-generation callback.
- [x] Verify failure, timeout, restart recovery, changed-patch rejection, and isolated apply using real temporary repositories/processes.
- [ ] Exercise a real microphone symptom and an approved live Astra repair; automated tests use deterministic agent processes.

## Current product follow-through
- [ ] Add `/v2` controls for provider enablement, model selection, fallback order, and an explicit opt-in multi-model compare mode.
- [x] Connect ARGO's UI/voice flow to the auditable coding-request record and the local Codex dispatcher. See [Self Repair](SELF_REPAIR.md).
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
