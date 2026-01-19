# ARGO Documentation Index (v1.0.0-voice-core)

Complete navigation for ARGO system documentation. All documentation current as of January 18, 2026.

**Note:** All documentation and code in this repository are covered by the repository's licensing terms. The ARGO Non-Commercial License applies to all specifications, designs, and implementation guides. Commercial use of any material in these docs requires a separate commercial license agreement.

---

## START HERE

### Critical Foundation

1. **[← Root README.md](../README.md)** — Project overview, what ARGO does, how to run
2. **[← Foundation Lock](../FOUNDATION_LOCK.md)** — What must NEVER be broken (critical reading)
3. **[← Release Notes](../RELEASE_NOTES.md)** — Why v1.0.0-voice-core matters, guarantees
4. **[← Getting Started](../GETTING_STARTED.md)** — Installation and first run

### For Developers Modifying Code

Read these BEFORE making any changes:
1. [Foundation Lock](../FOUNDATION_LOCK.md) — Non-negotiable constraints
2. [Phase 7B: State Machine](../PHASE_7B_COMPLETE.md) — Core control flow
3. [Phase 7B-2: STOP Interrupt](../PHASE_7B-2_COMPLETE.md) — Latency guarantees
4. [PR Guidelines](#making-changes-pr-guidelines) (at bottom of this page)

---

## System Architecture & Validation

### Phase 7B: State Machine (COMPLETE)

**[← Phase 7B: State Machine](../PHASE_7B_COMPLETE.md)** — Core control flow

SLEEP/LISTENING/THINKING/SPEAKING with deterministic transitions.
- SLEEP: Voice disabled, no ambient listening
- LISTENING: Awaiting SPACEBAR (PTT) or wake-word (future)
- THINKING: Processing query, STOP cuts LLM early
- SPEAKING: Playing audio response, STOP cancels playback <50ms

### Phase 7B-2: Integration & Hard STOP (COMPLETE)

**[← Phase 7B-2: Integration & STOP](../PHASE_7B-2_COMPLETE.md)** — STOP interrupt architecture

STOP dominance guaranteed:
- <50ms latency even during streaming
- Always preempts other operations
- Kills Piper process immediately
- Cancels LLM calls in progress
- Clears audio buffers
- Returns to LISTENING state

### Phase 7B-3: Command Parsing (COMPLETE)

**[← Phase 7B-3: Command Parsing](../PHASE_7B-3_COMPLETE.md)** — Safety gates and priority rules

---

## Voice System (Phase 7A)

### Phase 7A-2: Audio Streaming (COMPLETE)

**[← Phase 7A-2: Audio Streaming](../PHASE_7A2_STREAMING_COMPLETE.md)** — Piper TTS optimization

Time-to-first-audio reduced from 20-180s to 500-900ms:
- Incremental frame reading from Piper
- 200ms buffer threshold before playback starts
- Non-blocking stream via asyncio
- Profiling enabled: first_audio_frame, playback_started, streaming_complete
- STOP authority verified during streaming
- 5 test queries validated (short/medium/long responses)

### Voice Mode: Stateless Execution (COMPLETE)

**[← Option B: Confidence Burn-In](../OPTION_B_BURNIN_REPORT.md)** — Validation results

14/14 tests passed, 0 anomalies, 95% confidence:
- Tier 1 (Fundamental): 5/5 passed
  - Stateless execution (no history injection)
  - Memory system disabled
  - System prompt guardrail active
  - No context bleed
  - STOP responsiveness maintained
- Tier 3 (Edge Cases): 3/3 passed
  - Rapid stop sequences
  - Overlapping input handling
  - Quiet environment transcription
- Tier 4 (Streaming): 3/3 passed
  - Long responses
  - Interruption during playback
  - Resource usage (CPU <5%)

### Phase 7A-3a: Wake-Word Design (COMPLETE - PAPER-ONLY, NO CODE)

**IMPORTANT: Phase 7A-3a is design-only. Implementation pending approval.**

**[← Phase 7A-3: Wake-Word Design](../PHASE_7A3_WAKEWORD_DESIGN.md)** — 11-section architecture

Comprehensive design covering:
- Activation model (LISTENING active, SLEEP/THINKING/SPEAKING inactive)
- PTT coexistence (SPACEBAR pauses wake-word)
- STOP dominance (<50ms cancellation, buffer clearing)
- Resource model (<5% idle CPU, lightweight detector)
- False-positive strategy (silent failures via ambiguity handler)
- State machine integration (wake-word requests, doesn't override)
- Priority rules (STOP > SLEEP > PTT > wake-word > idle)
- Edge cases (all documented)
- Failure modes (all documented)
- Validation checklist (pre-implementation criteria)

**[← Wake-Word Decision Matrix](../WAKEWORD_DECISION_MATRIX.md)** — 15-table reference

Comprehensive trigger-outcome matrices:
- Master matrix (state × input combinations)
- Behavior tables for SLEEP, LISTENING, THINKING, SPEAKING
- False-positive matrix (confidence thresholds)
- PTT override precedence
- STOP dominance matrix
- State transition guards
- Edge case resolution
- Failure mode resolution
- Test matrix (for future validation phase)
- Sign-off matrix (acceptance criteria)

**[← Go/No-Go Checklist](../PHASE_7A3_GONO_CHECKLIST.md)** — 14 acceptance criteria

14 acceptance criteria + 6 auto-fail conditions:
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
- No hand-waving
- All criteria met (master gate)
- 6 NO-GO auto-fail conditions (design is abandoned if any triggered)

---

## Existing Documentation

### Architecture & Design

**[← System Architecture](../ARCHITECTURE.md)** — Memory, preferences, voice system design

**[← Artifact Chain Architecture](architecture/artifact-chain.md)** — Three-layer artifact system (Transcription, Intent, Planning)

**[← Frozen Layers](../FROZEN_LAYERS.md)** — Official freeze of v1.0.0-v1.3.0 safety chain

### Feature Planning

**specs/master-feature-list.md** — The canonical scope document

Lists all 200 planned capabilities, grouped by domain (voice, lighting, climate, media, automation, security, etc.). Also defines explicit non-behaviors (what ARGO refuses to do).

Use this to:
- Understand what ARGO is designed to do
- Verify scope boundaries
- Check implementation status of any capability
- Understand safety constraints

## architecture/

**raspberry-pi-node.md** — Explains how Raspberry Pi nodes function as sensory and output peripherals. Covers microphone input, camera input, speaker output, HDMI display control, and input switching. Emphasizes that all authority stays on ARGO Core.

Use this to:
- Understand the distributed system design
- Learn how trust is partitioned between Core and Pis
- Understand failure behavior and recovery
- Plan Pi deployment

## system/

*Existing architecture documentation*

**architecture.md** — Technical overview of memory system (TF-IDF + topic fallback), preference detection and storage, recall mode mechanics, voice system, conversation browsing, transcription artifacts, and intent artifacts.

Use this to:
- Understand how memory retrieval works
- Learn preference detection patterns
- Understand recall mode formatting rules
- Understand voice compliance enforcement
- Learn transcription and intent artifact architecture

## decisions/

---

## Peripheral & Deployment

**[← Raspberry Pi Architecture](architecture/raspberry-pi-node.md)** — Peripheral design and trust boundaries

---

## Phase Completion Status

| Phase | Status | Key Deliverable | Date |
|-------|--------|-----------------|------|
| Phase 7B | ✓ COMPLETE | State machine (SLEEP/LISTENING/THINKING/SPEAKING) | Jan 2026 |
| Phase 7B-2 | ✓ COMPLETE | Integration & STOP interrupt (<50ms) | Jan 2026 |
| Phase 7B-3 | ✓ COMPLETE | Command parsing + safety gates | Jan 2026 |
| Option B | ✓ COMPLETE | Confidence burn-in (14/14 tests, 0 anomalies) | Jan 2026 |
| Phase 7A-2 | ✓ COMPLETE | Audio streaming (TTFA 500-900ms) | Jan 2026 |
| Phase 7A-3a | ✓ COMPLETE | Wake-word design (paper-only) | Jan 2026 |
| Phase 7A-3 | ⏳ PENDING | Wake-word implementation (awaiting design approval) | TBD |
| Phase 7D | ❌ DEFERRED | Voice personality (Allen identity) | TBD |
| Tools | ❌ DEFERRED | Tool invocation system | TBD |

---

## Release Guarantees (v1.0.0-voice-core)

These are NON-NEGOTIABLE. All future releases must maintain these.

1. **State machine is authoritative** — No component bypasses state transitions
2. **STOP always interrupts** — <50ms latency, even during audio streaming
3. **Voice mode is stateless** — No prior conversation context injection
4. **SLEEP is absolute** — Voice commands ignored, SPACEBAR PTT only
5. **Prompt hygiene enforced** — System instruction prevents context leakage
6. **Audio streaming is non-blocking** — TTF-A ~500-900ms

---

## What's Locked vs. Extensible

### LOCKED (Foundation - No Silent Changes)

Core files that are part of the foundation lock:
- `wrapper/argo.py` — Main execution engine
- `core/output_sink.py` — Audio output abstraction
- `wrapper/command_parser.py` — Command parsing
- State machine logic (SLEEP/LISTENING/THINKING/SPEAKING)
- STOP interrupt handler

Future changes to locked files must:
- Be additive (no removal)
- Come through PR with explicit review
- Maintain all existing guarantees
- Include performance testing

### EXTENSIBLE (Designed for Addition)

- Wake-word detector (not yet added)
- Tool invocation system (out of scope)
- Voice personality (deferred)
- Memory persistence backends
- Peripheral system (Raspberry Pi)
- Custom command handlers
- New intent types

---

## Making Changes: PR Guidelines

### If You Modify Locked Files

**Allowed PRs:**
- "Add optional event logging" (additive)
- "Implement new command type" (doesn't modify core)
- "Optimize streaming buffer" (with performance testing)

**Rejected PRs:**
- "Remove STOP latency check" (breaks guarantee)
- "Disable voice mode statelessness" (breaks guarantee)
- "Refactor state machine transitions" (silent change)
- "Add background listening" (breaks design)

### If You Add New Functionality

Must include:
- Design document (if complex)
- Tests (verify existing guarantees)
- PR description (what and why)
- Performance metrics (if touching timing paths)

### If You Fix a Bug

Must include:
- Bug description
- Root cause
- Fix explanation
- Regression test

---

## Quick Navigation

**First time reading?** Start with [Root README.md](../README.md) → [Foundation Lock](../FOUNDATION_LOCK.md) → [Getting Started](../GETTING_STARTED.md)

**Want architecture details?** [Phase 7B State Machine](../PHASE_7B_COMPLETE.md) → [Phase 7B-2 STOP](../PHASE_7B-2_COMPLETE.md) → [Phase 7B-3 Parsing](../PHASE_7B-3_COMPLETE.md)

**Curious about voice?** [Phase 7A-2 Streaming](../PHASE_7A2_STREAMING_COMPLETE.md) → [Option B Results](../OPTION_B_BURNIN_REPORT.md) → [Voice Mode Design](../PHASE_7B_COMPLETE.md)

**Need complete scope?** [Master Feature List](specs/master-feature-list.md)

**Implementing a feature?** Check the feature list, read [Foundation Lock](../FOUNDATION_LOCK.md), then follow [PR Guidelines](#making-changes-pr-guidelines)

**Debugging?** Check logs and review relevant architecture doc

---

*Last Updated: January 18, 2026 | v1.0.0-voice-core*

**For questions about licensing, see [LICENSE](../LICENSE).**