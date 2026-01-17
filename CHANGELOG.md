# Changelog

All notable changes to Argo are documented here.

## [1.2.0] – 2026-01-17

### Added
- **Executable Intent System** (Planning Layer, No Execution)
  - ExecutableIntent engine translates confirmed intents → executable plans
  - ExecutablePlan class with full step decomposition and metadata
  - ExecutableStep with action types, safety levels, and rollback procedures
  - PlanDeriver with derivation rules for 5 intent verbs (write, open, save, show, search)
  - Safety analysis: SAFE, CAUTIOUS, RISKY, CRITICAL levels
  - Rollback capability tracking: FULL, PARTIAL, NONE
  - Confirmation gate counter: tracks confirmations needed before execution
  - `plan_and_confirm()` function in argo.py with explicit review gate
  - ExecutablePlanStorage for session-only plan management
  - Full audit logging to `runtime/logs/executable_intent.log`
  - Complete test suite (26/26 tests passing, test_executable_intent.py)

- Planning Features
  - Deterministic plan derivation (same intent → same plan)
  - Step-by-step plan decomposition with metadata
  - Risk analysis and mitigation strategies
  - Rollback procedures defined for state-changing operations
  - Fallback for unknown intents (generic planning)
  - Plan status tracking: derived → awaiting_confirmation → ready_for_execution
  - Full plan summary() with human-readable format

- Safety Features
  - Zero execution (plans created but not executed)
  - Explicit confirmation counts (how many approvals needed)
  - Irreversible action detection
  - Rollback procedures for all reversible operations
  - Session isolation (plans not persisted across sessions)

### Design Philosophy
- Planning is NOT execution
- Plans are deterministic and predictable
- All state-changing operations include rollback procedures
- Confirmation gates are explicit and counted
- Auditability: full JSON logging of all plans
- No side effects during planning

### Integration Points
- Executable intent engine integrated into wrapper/argo.py
- New function: `plan_and_confirm(intent_artifact)` for plan review
- New module: wrapper/executable_intent.py (700+ lines)
- New documentation: docs/intent/executable_intent.md
- Full API reference with examples and usage patterns

### Architecture
- v1.0.0: Audio → TranscriptionArtifact
- v1.1.0: Text → IntentArtifact (parsed intent)
- v1.2.0: IntentArtifact → ExecutablePlan (planning, no execution)
- v1.3.0: ExecutablePlan → Execution (future)

## [1.1.0] – 2026-01-17

### Added
- **Intent Artifact System** (Non-Executable Parsing Layer)
  - IntentArtifact class for structured intent representation
  - Deterministic command grammar parser (write, open, save, show, search)
  - CommandParser with ambiguity preservation (never guesses)
  - IntentStorage for session-only artifact management
  - `intent_and_confirm()` function with explicit confirmation gate
  - Zero side effects: parsing only, no execution whatsoever
  - Full audit trail logging to `runtime/logs/intent.log`
  - Complete test suite (test_intent_artifacts.py)

- Intent Parsing Features
  - Supported verbs: write, open, save, show, search
  - Structured output: {verb, target, object, parameters, ambiguity}
  - Confidence scoring (0.0-1.0)
  - Ambiguity preservation for user clarity
  - Clean pipeline: Audio → Transcription → Intent → (future) Execution

- Confirmation Gate for Intent
  - Display parsed intent structure to user
  - Require explicit approval before downstream processing
  - Approved status is NOT execution (preparation only)
  - All confirmation outcomes tracked

### Design Philosophy
- Status "approved" means "user said yes" NOT "execute"
- Ambiguity is preserved, never inferred
- Only confirmed sources allowed (typed or transcription)
- Session-only storage (no auto-save to memory)
- Pure parsing layer with zero side effects

### Integration Points
- Imports added to wrapper/argo.py
- New module: wrapper/intent.py (600+ lines)
- New documentation: docs/intent/artifacts.md
- Full API reference with examples

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
