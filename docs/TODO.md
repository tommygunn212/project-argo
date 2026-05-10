# TODO / Next Steps (Post-Validation)

Short list of deferred or optional work items. No refactors implied.

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
