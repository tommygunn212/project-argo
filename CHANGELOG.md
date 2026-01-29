# Changelog

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
