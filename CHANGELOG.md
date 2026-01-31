# Changelog

## v1.7.0 — Core Memory & STT Hardening (Stable)

### Added
- Explicit-only memory system with FACT / PROJECT / EPHEMERAL namespaces
- Read-only memory introspection commands
- Whisper STT hint injection (local-only)
- Audio hygiene and silence rejection
- Deterministic chaos stress testing

### Fixed
- Implicit memory writes (eliminated)
- Audio-induced hallucinations
- Pipeline instability under interruption

### Security / Guarantees
- Memory cannot trigger actions
- No cloud dependencies
- No eval / exec paths
- Deterministic restart behavior

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
