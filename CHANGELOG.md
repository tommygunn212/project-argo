# Changelog

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
