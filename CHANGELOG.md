# Changelog

All notable changes to Argo are documented here.

## [1.0.0] – 2026-01-17

### Added
- **Whisper Audio Transcription** with explicit confirmation gate
  - TranscriptionArtifact for full auditability
  - No blind automation: user sees and approves every transcript
  - Deterministic transcription (same audio → same text every time)
  - `--transcribe <audio.wav>` CLI flag for transcription + processing
  - Comprehensive logging to `runtime/audio/logs/transcription.log`
  - Session persistence of transcription artifacts

- Audio-to-text confirmation flow
  - Display: "Here's what I heard: '<transcript>'. Proceed?"
  - Only explicit user confirmation allows downstream processing
  - Rejection preserves option to re-record
  - All outcomes (confirmed/rejected/failed) tracked

- Integration testing for transcription + ARGO pipeline
  - Unit tests for artifact storage and confirmation
  - Integration test suite (test_argo_whisper_integration.py)
  - Manual testing guide for end-to-end validation

### Enhanced
- `wrapper/argo.py` now includes transcription module
- Argument parsing supports `--transcribe` flag
- Dependencies: Added openai-whisper
- Documentation: Added `docs/transcription/whisper.md`

- Conversation browsing (list, show by date/topic, summarize, open)
- User preference detection and persistence (tone, verbosity, humor, structure)
- Memory hygiene enforcement (recall queries never stored)
- Voice validation safety net (traction control model)
- Interactive CLI mode with natural conversation flow
- PowerShell alias integration (`ai` command)

### Core Systems
- TF-IDF memory retrieval with topic fallback (Phase 2a)
- Three-tier memory fallback (TF-IDF → Topic → Recency)
- Preferences auto-detection via pattern matching
- Mode detection (recall vs generation)
- Explicit intent-based routing (no auto-detection)

### Design
- Safety-first validator (not a style cop)
- Read-only conversation browsing (no modification)
- Memory factual summary only (no interpretation)
- Human control over all inference

### Initial Release
First stable release with memory, preferences, recall, and browsing fully integrated and tested.
