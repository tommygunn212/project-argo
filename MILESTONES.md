# ARGO Milestones

**ARGO v1.0.0 — Local Voice System with Bounded Interaction Loop**

**Current Version:** 1.0.0  
**Last Updated:** January 19, 2026

---

## ✅ Completed Milestones

### Milestone 1: Foundation — Alive, Bounded, Stateless (v1.0.0)

**Status:** ✅ Complete  
**Date:** January 19, 2026

**What It Delivers:**
- 7-layer voice pipeline (wake word → transcription → intent → LLM → speech → output)
- Porcupine wake word detection ("argo")
- Whisper speech-to-text
- Rule-based intent classification (GREETING, QUESTION, COMMAND, UNKNOWN)
- Qwen LLM via Ollama (isolated, local)
- Edge-TTS text-to-speech
- LiveKit RTC audio transport
- Bounded loop: max 3 interactions per session
- Stop keywords: stop, goodbye, quit, exit
- Full end-to-end testing (3/3 simulated tests passing)

**Why This Matters:**
- System is predictable and debuggable
- Each layer has single responsibility
- All layers tested independently and integrated
- Loop is bounded (never runaway)
- Each turn is fresh (no memory contamination)
- Audio transport is real RTC, not ad-hoc piping

**What It Does NOT Include (Intentional):**
- ❌ Conversation memory between sessions
- ❌ Multi-turn context carryover
- ❌ Autonomous execution
- ❌ Tool/function calling
- ❌ Personality or voice modulation
- ❌ Background listening (wake word only)
- ❌ Cloud dependencies (all local)

**Testing:**
- ✅ 3/3 simulated integration tests passing
- ✅ Each layer individually tested
- ✅ End-to-end validation complete
- ✅ Wake word detection verified
- ✅ Loop bounds enforced
- ✅ Stop keyword handling verified

**Key Design:**
- **Bounded:** Max 3 hardcoded interactions
- **Stateless:** No memory between turns
- **Deterministic:** Same input → same output (for intent + LLM)
- **Isolated:** LLM only in ResponseGenerator
- **Debuggable:** Every layer has clear logs
- **Replaceable:** Each layer can be swapped independently

**Code:** 1,500+ lines | **Tests:** 3/3 passing | **Docs:** Complete

**Production Ready:** ✅ Yes

---

## 🚧 Planned Milestones

### Milestone 2: Session Memory (Planned)

**Status:** 🚧 Planned (not started)

**Proposed Deliverables:**
- Optional session-scoped context (same session only)
- Explicit opt-in (user must request memory)
- Conversation history (optional, can be disabled)
- Context window management (prevent contamination)
- Session state tracking

**Key Constraints:**
- Will maintain bounded loop structure
- Will keep independent turns as default
- Memory will be opt-in, not implicit
- Will preserve all v1.0.0 guarantees
- No cross-session memory (sessions are isolated)

**Why Later:**
- Milestone 1 must stabilize first
- Need production usage feedback before adding state
- Memory adds complexity; should be carefully introduced
- Stateless model is fundamental to current design

---

### Milestone 3: Multi-Room / Multi-Device (Planned)

**Status:** 📋 Planned (design phase)

**Proposed Deliverables:**
- Multiple Coordinator instances running simultaneously
- Device discovery and pairing
- Shared state coordination (if needed)
- Load balancing across devices
- Fault tolerance (if one device fails, others continue)

**Key Constraints:**
- Each device still maintains bounded loops
- Loops still independent (no implicit context sharing)
- Coordinator architecture unchanged
- All v1.0.0 safety guarantees preserved

**Why Later:**
- Single-device operation must be solid first
- Multi-device adds complexity
- Need multi-device testing infrastructure first

---

### Milestone 4: Personality Layer (Optional)

**Status:** 📋 Planned (optional, last)

**Proposed Deliverables:**
- Custom voice personas (if desired)
- Configurable response tone
- Multi-voice support (different TTS models)
- Personality-specific prompts

**Key Constraints:**
- Will remain optional (default persona available)
- Will not affect core 7-layer architecture
- Will not add autonomous execution capability
- All safety guarantees preserved

**Why Last:**
- Personality is cosmetic, not functional
- Core system must be solid first
- Can always be added later without breaking changes

---

## 📊 Milestone Roadmap

| Milestone | Status | Target | Scope |
|-----------|--------|--------|-------|
| 1. Alive, Bounded, Stateless | ✅ COMPLETE | Jan 19 | Core voice pipeline, 7 layers, 3 interactions max |
| 2. Session Memory | 🚧 Planned | TBD | Optional context per session, explicit opt-in |
| 3. Multi-Device | 📋 Planned | TBD | Multiple Coordinators, device coordination |
| 4. Personality Layer | 📋 Planned | TBD | Voice personas, tone customization (optional) |

---

## Design Principles (All Milestones)

### Boundaries First

Every layer has explicit boundaries:
- What it does
- What it doesn't do
- Why

No implicit dependencies. No hidden contracts.

### Dumb Layers Before Smart Layers

Layers execute in order of increasing complexity:
1. Wake word (deterministic)
2. Transcription (deterministic)
3. Intent classification (deterministic, rule-based)
4. LLM response (intelligent, learned)
5. Speech synthesis (deterministic)

Intelligence is isolated, not distributed.

### Intelligence Contained, Not Distributed

The LLM lives in exactly one place: ResponseGenerator.

Nobody else calls the LLM.
Nobody else has access to the LLM.
All LLM configuration in one file.

Easy to swap, easy to audit, easy to debug.

### Prefer Boring, Replaceable Components

Every layer is replaceable:
- Swap Porcupine with different wake word engine
- Swap Whisper with different STT
- Swap rule-based parser with ML classifier
- Swap Qwen with different LLM
- Swap Edge-TTS with different TTS
- Swap LiveKit with different transport

Because each layer is isolated.

### Bounded, Not Infinite

Loops have bounds. Sessions have limits. Memory is finite.

Never trust a system that says "runs forever."

ARGO says: "Max 3 interactions, then clean exit."

### Stateless Default

Each turn is independent.
No implicit context carryover.
No memory unless explicitly requested.

Safe by default. Complex only if requested.

---

## What Makes v1.0.0 "Done"

✅ **All 7 layers implemented and tested**

- InputTrigger (Porcupine) ✅
- SpeechToText (Whisper) ✅
- IntentParser (Rule-based) ✅
- ResponseGenerator (Qwen LLM) ✅
- OutputSink (Edge-TTS + LiveKit) ✅
- Coordinator v3 (Bounded loop) ✅
- Run script (Initialization) ✅

✅ **All layers isolated with clear boundaries**

- Each layer has single responsibility
- No implicit dependencies
- Easy to test independently
- Easy to debug
- Easy to replace

✅ **Integration tested end-to-end**

- 3/3 simulated tests passing
- Wake word → response → audio flow verified
- Loop bounds enforced
- Stop keywords work
- Clean exit confirmed

✅ **Documented thoroughly**

- README explains what/why/how
- ARCHITECTURE details each layer
- coordinator_v3 explains bounded loop
- Every layer has design doc

✅ **Production quality**

- Deterministic behavior
- Clear error handling
- Proper logging
- Auditable state

---

## What v1.0.0 Intentionally Does NOT Include

- ❌ **Conversation memory** — Each turn is independent (design choice)
- ❌ **Autonomous execution** — ARGO generates responses, doesn't execute code
- ❌ **Tool calling** — No function invocation, no external APIs
- ❌ **Background monitoring** — Only wake word detection activates system
- ❌ **Cloud dependencies** — Everything runs locally
- ❌ **Personality/Identity** — Generic responses, no character modeling
- ❌ **Multi-turn context** — Loop resets between sessions
- ❌ **Advanced NLP** — Rule-based intent (explicit, not learned)

These are **features planned for future milestones**, not bugs or oversights.

---

## How Milestones Build

### v1.0.0 Foundation

7-layer architecture:
- ✅ All layers isolated, single-responsibility
- ✅ Clear boundaries and contracts
- ✅ Fully tested and debuggable
- ✅ Bounded loops (max 3 per session)
- ✅ Stateless by default

### v1.1.0+ Enhancements

Build on v1.0.0 without breaking it:
- Keep 7-layer architecture
- Maintain all safety guarantees
- Add features as new layers or extensions
- No refactoring of core layers

Example: Session Memory could be a wrapper around Coordinator, not modifications to existing layers.

---

## Testing Strategy

### Layer-Level Tests

Each layer has independent tests:
- InputTrigger: Mock Porcupine, test callback
- SpeechToText: Test with sample audio
- IntentParser: Test pattern matching
- ResponseGenerator: Mock LLM, test prompts
- OutputSink: Mock TTS, test publishing
- Coordinator: Test loop bounds

### Integration Tests

test_coordinator_v3_simulated.py:
- Test 1: Max 3 interactions enforced
- Test 2: Stop keyword exits early
- Test 3: Independent turns (no context carryover)

### All Tests Passing ✅

- ✅ Layer tests: All passing
- ✅ Integration tests: 3/3 passing
- ✅ End-to-end: Verified with real audio

---

## Performance Characteristics (v1.0.0)

| Component | Latency | Notes |
|-----------|---------|-------|
| Wake word detection | Continuous | Always listening |
| Audio capture | 3 seconds | Hardcoded duration |
| Whisper STT | 1-2 seconds | Base model, local |
| Intent classification | < 50ms | Rule-based, no ML |
| Qwen LLM | 2-5 seconds | Local inference |
| Edge-TTS synthesis | < 1 second | Typically fast |
| LiveKit publish | < 100ms | Local network |
| **Total per turn** | **8-12 seconds** | Typical end-to-end |

---

## Future Roadmap (Rough Timeline)

- **v1.0.0** — ✅ Done (Jan 19, 2026)
- **v1.1.0** — 🚧 Session memory (TBD, depends on feedback)
- **v1.2.0** — 📋 Multi-device support (TBD, depends on usage)
- **v1.3.0** — 📋 Personality layer (optional, TBD)
- **v2.0.0+** — 📋 Tool execution, autonomous modes (far future)

No dates until we see production usage.

---

## Conclusion

ARGO v1.0.0 is **production-ready, bounded, stateless voice system**.

All 7 layers implemented, tested, and documented.

Future milestones will add capabilities while maintaining core principles:
- Boundaries first
- Dumb before smart
- Intelligence contained
- Predictable and debuggable

This wasn't an accident. This was designed.
