# CHANGELOG — ARGO Version History

All notable changes to ARGO are documented in this file.  
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [Unreleased] — VAD-only pipeline + UI debugger

### Added
- Always-listening VAD pipeline (wake word removed)
- UI debugger WebSocket stream with status + latency cards
- Piper voice integration (local TTS)

### Changed
- Pipeline serialized with interaction lock to prevent overlap
- WebSocket server hardened against handshake errors
- Frontend served from local `/frontend/index.html`

### Fixed
- Whisper input shape handling for single-channel audio
- TTS playback cut-offs from partial audio writes

## [v1.0.0-voice-core] — 2026-01-18

### Foundation Release: Voice System Complete

This release establishes the foundation ARGO voice system with proven stateless execution, fast audio streaming, and guaranteed interrupt authority. The system is auditable, predictable, and production-ready for voice-based queries with explicit STOP control.

**Release Tag:** [v1.0.0-voice-core](https://github.com/tommygunn212/project-argo/releases/tag/v1.0.0-voice-core)

### Added

#### Phase 7B: Deterministic State Machine ✅

- New state machine: SLEEP → LISTENING → THINKING → SPEAKING
- Deterministic transitions with explicit guards
- No loops, no undefined paths, fully auditable
- State change latency: <50ms profiled
- SLEEP blocks voice input absolutely
- LISTENING gates PTT and future wake-word
- THINKING transitions to SPEAKING on LLM response
- SPEAKING returns to LISTENING on completion or STOP

#### Phase 7B-2: Hard STOP Interrupt (<50ms) ✅

- STOP preempts all operations (Piper TTS, LLM calls, state changes)
- Guaranteed <50ms latency from command parser to LISTENING state
- Piper process killed immediately (<10ms)
- LLM calls cancelled, context preserved for future use
- Audio buffer cleared on interrupt
- Independent interrupt handler (not queued behind other ops)
- Latency guarantee: <50ms verified in testing, locked for all future releases

#### Phase 7B-3: Command Parsing with Safety Gates ✅

- Explicit command types (STOP, SLEEP, PTT, etc.)
- Parser validates syntax before execution
- Priority rules prevent conflicts: STOP > SLEEP > PTT > wake-word > idle
- Graceful error handling (returns to LISTENING)
- CLI formatting standardized

#### Phase 7A-2: Audio Streaming (Non-Blocking) ✅

- Incremental Piper TTS frame reading
- Buffered playback with 200ms threshold before audio starts
- Time-to-first-audio: 500-900ms (5 test queries averaged)
  - "hello world": 537.9ms TTFA
  - "what is machine learning?": 830.6ms TTFA
  - Baseline improvement: 40-360x faster (from 20-180s full synthesis)
- STOP authority maintained during streaming (<50ms latency verified)
- Profiling enabled: first_audio_frame, playback_started, streaming_complete timestamps
- Background thread + asyncio for non-blocking playback
- Sounddevice float32 normalization (-1.0 to 1.0 range)
- Architecture: Replaced blocking Piper wait with `_stream_audio_data()` and `_stream_to_speaker()`

#### Voice Mode: Stateless Execution ✅

- Voice mode parameter (`voice_mode=True`) disables memory system entirely
- Memory queries skipped: zero history injection
- System prompt guardrail: `PRIORITY 0: You are in voice mode. Do not reference prior conversations.`
- Priority layers dominate all other prompts (defense in depth)
- Single-turn only: no multi-turn conversation in voice mode
- Stateless guarantee: audited and validated

#### Push-to-Talk (PTT) with Explicit Control ✅

- SPACEBAR activates Whisper transcription
- Audio captured, transcribed, submitted as query
- SPACEBAR or "STOP" interrupts transcription
- <50ms interrupt latency

#### Environment Persistence ✅

- Python-dotenv integration
- .env file auto-loads on subprocess startup
- Configuration persists across calls
- No secrets in code or env vars

#### Option B Confidence Burn-In Validation ✅

- **14/14 tests passed** (100% success rate)
- **Zero anomalies, zero false positives**
- **95% confidence assessment**

Tier 1 (Fundamental): 5/5 passed
- Stateless execution (no history)
- Memory disabled in voice mode
- System prompt guardrail active
- No context bleed across queries
- STOP responsiveness maintained

Tier 3 (Edge Cases): 3/3 passed
- Rapid stop sequences
- Overlapping input handling
- Quiet environment transcription

Tier 4 (Streaming): 3/3 passed
- Long responses (full streaming)
- Interruption during playback
- Resource usage (CPU <5% idle)

#### Phase 7A-3a: Wake-Word Detection Design (Paper-Only) ✅

Comprehensive architecture for future wake-word feature (design complete, no code):

1. **PHASE_7A3_WAKEWORD_DESIGN.md** — 11-section architecture
   - Activation: LISTENING state active only
   - PTT coexistence: SPACEBAR pauses wake-word
   - STOP dominance: <50ms cancellation verified
   - Resource model: <5% idle CPU target
   - False-positive strategy: Silent failures
   - State machine: No bypass guarantee
   - Priority rules: STOP > SLEEP > PTT > wake-word > idle
   - Edge cases: All documented (false wake during PTT, STOP mid-detection, SLEEP bypass attempts)
   - Failure modes: Detector crash, high FP, CPU spike, recovery procedures
   - Validation: Pre-implementation checklist

2. **WAKEWORD_DECISION_MATRIX.md** — 15-table reference
   - Master trigger-outcome matrix (state × input combinations)
   - Detailed behavior for each state (6 tables: SLEEP, LISTENING, THINKING, SPEAKING)
   - False-positive matrix (confidence thresholds, outcomes)
   - PTT override precedence
   - STOP dominance matrix
   - State transition guards
   - Edge case resolution
   - Failure mode resolution
   - Test matrix (for future Phase 7A-3 validation)
   - Sign-off matrix (acceptance criteria)

3. **PHASE_7A3_GONO_CHECKLIST.md** — 14 acceptance criteria
   - Architecture fully specified (no vague language)
   - STOP dominance unquestionable
   - State machine not bypassed
   - False positives are silent
   - PTT always wins
   - SLEEP is absolute
   - CPU targets met (<5% idle)
   - Detector model selected & tested
   - No new heavy dependencies
   - Integration points clear
   - Test plan achievable
   - No hand-waving (self-assessment)
   - All criteria met (master gate)
   - 6 NO-GO auto-fail conditions

Status: Design phase complete. Implementation pending Phase 7A-3 approval.

### Fixed

- **Audio garbling from WAV output** — Switched Piper to `--output-raw` mode (raw PCM, no header corruption)
- **Environment variables not loading** — Python-dotenv loads .env at startup
- **Voice mode context leakage** — Memory disabled + system prompt guardrail enforced
- **STOP not preempting audio** — Incremental streaming decouples synthesis from playback
- **CLI formatting violations** — Standardized help generation and output formatting

### Architecture Decisions

1. **State Machine Authority** — Single control flow point, no bypasses
2. **STOP as Hard Interrupt** — <50ms latency, user manual override always wins
3. **Voice Mode Stateless** — Zero history injection, single-turn only
4. **SLEEP Absolute** — Voice listener process disabled, ambient input impossible
5. **Prompt Priority Layers** — Defense in depth, PRIORITY 0 dominates all others
6. **Non-Blocking Streaming** — Audio playback doesn't block user input

### Known Limitations

- **No wake-word detection** (design complete, implementation pending Phase 7A-3)
- **No voice personality** (deferred to Phase 7D)
- **No tool invocation** (out of scope for v1.0.0)
- **Voice mode is single-turn** (no multi-turn history)

### Security & Guarantees

All runtime guarantees are **NON-NEGOTIABLE** for future releases:

1. State Machine Authority — No component bypasses state transitions
2. STOP Dominance — <50ms latency, always preempts
3. Voice Statelessness — Zero history injection in voice mode
4. SLEEP Absoluteness — Voice listener disabled, no ambient listening
5. Prompt Hygiene — Priority layers prevent context leakage
6. Streaming Non-Blocking — Audio doesn't block user control

### Upgrade Path

- **To v1.1.0** (Wake-Word): After Phase 7A-3 implementation. Additive feature, no breaking changes.
- **To v2.0.0** (Full Release): After Phase 7D-E (voice personality, multi-turn voice, tools). May include breaking changes.

---

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

### Design Philosophy
- Planning is NOT execution
- Plans are deterministic and predictable
- All state-changing operations include rollback procedures
- Confirmation gates are explicit and counted
- Auditability: full JSON logging of all plans
- No side effects during planning

---

## [1.1.0] – 2026-01-17

### Added
- **Intent Artifact System** (Non-Executable Parsing Layer)
  - IntentArtifact class for structured intent representation
  - Deterministic command grammar parser
  - CommandParser with ambiguity preservation
  - `intent_and_confirm()` function with explicit confirmation gate
  - Zero side effects: parsing only, no execution

### Design Philosophy
- Status "approved" means "user said yes" NOT "execute"
- Ambiguity is preserved, never inferred
- Session-only storage (no auto-save to memory)
- Pure parsing layer with zero side effects

---

## [1.0.0] – 2026-01-17

### Added
- **Whisper Audio Transcription** with explicit confirmation gate
- Conversation browsing (list, show by date/topic, summarize)
- User preference detection and persistence
- Memory hygiene enforcement (recall queries never stored)
- Interactive CLI mode with natural conversation flow

### Core Systems
- TF-IDF memory retrieval with topic fallback
- Three-tier memory fallback (TF-IDF → Topic → Recency)
- Preferences auto-detection via pattern matching
- Mode detection (recall vs generation)

### Design Philosophy
- Safety-first validator
- Read-only conversation browsing
- Memory factual summary only
- Human control over all inference
