# Changelog

## v1.6.1 — Deterministic Core Stabilization (2025-02-02)

### Added
- Canonical / deterministic commands now bypass STT confidence gates entirely
- Unresolved noun phrase detection triggers clarification instead of LLM fallback
- Six missing method stubs added to pipeline.py for interrogative detection and clarification flow
- VAD_END minimum voiced speech threshold set to 300ms (reduces false triggers from grunts/noise)
- Natural language phrasing support: COUNT ("let's count to 5", "give me 3 numbers"), SYSTEM HEALTH ("how's my computer doing", "anything wrong with my system"), APP CONTROL ("shut notepad", "close the browser")

### Fixed
- Type annotations corrected across pipeline.py (Optional[str] for nullable returns)
- focus_app → focus_app_deterministic consistency
- Guarded None values for add_memory, play_by_genre, play_by_keyword
- Unbound variable guards for all edge cases in pipeline execution
- Test harness safety: removed import-time sys.exit() from 4 test files
- bare except: clauses replaced with logged exceptions throughout codebase

### Known Issues (Not Blocking)
- 12 pre-existing test failures (test debt) — tracked in TEST_DEBT.md
- test_stt_hardening.py: outdated function signature
- test_clarification_gate.py: assertion mismatch
- test_confirmable_identity_memory.py: harness issues
- test_piper_integration.py: env configuration
- test_coordinator_v1/v2: integration test issues

---

## v1.6.0 — Voice Stability & UX Refinement (Stable)

### Core Stability
- Fixed pipeline state machine to allow THINKING → LISTENING
- Prevents illegal transitions when TTS is suppressed
- Eliminates state-machine warnings and deadlocks
- Deterministic behavior confirmed via logs
- Barge-in handling fully stabilized
- Forced audio release during TTS works correctly
- Clean recovery to LISTENING with no duplicate transitions

### Audio + Interaction Flow
- TTS suppression paths now terminate cleanly
- Silence and low-confidence exits no longer poison pipeline state
- Interaction lifecycle consistently reaches INTERACTION_END

### Intent + UX Improvements
- Canonical routing refined to prevent misclassification
- Identity questions no longer misrouted as SYSTEM_HEALTH
- Keyword-only canonical bypass reduced
- MUSIC intent handling improved:
	- Confidence guards scoped by intent (music commands more tolerant)
	- Prevents false rejections for short, common commands
	- MUSIC intent no longer falls back to open-ended LLM responses
	- Failed matches now request clarification instead of hallucinating

### Safety & Governance
- No changes to gate system (validation, permission, safety, resource, audit)
- No loosening of security or execution constraints
- Behavior improvements are scoped and deterministic

## v1.5.0 – Hardened Core Baseline
- Deterministic system health + disk queries (no LLM)
- Conversational system status formatting (voice-friendly)
- Expanded hardware specs (CPU, memory, GPU, board, BIOS)
- Local music index (data/music_index.json) + rebuild script
- Music hardening and stricter matching for playback
- OpenRGB lighting control via deterministic commands
- Audio device selection via config.json
- Atomic persistence for memory and prefs
- TOCTOU execution guards
- Async orchestration and TTS worker thread
- Stabilized runtime core

## v1.0.0 – Initial Public Release
- Voice-first local AI assistant
- Wake word detection, STT, LLM, TTS pipeline
