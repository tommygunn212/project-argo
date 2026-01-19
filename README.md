# ARGO

**Autonomous-Resistant Governed Operator**

ARGO is a local-first AI control system built to act only under explicit instruction.
It runs on your main PC. Raspberry Pi nodes serve strictly as sensory peripherals.
All intelligence, memory, and authority remain on the core system.

ARGO does not guess intent.
It does not execute silently.
It does not simulate autonomy.

Every action is either explicitly confirmed or executed under a rule you defined.
Every action is logged.
If you override ARGO with a physical control, ARGO backs off immediately.

ARGO exists for one reason: **you remain in control**.

It amplifies your intent without replacing it.
It assists without improvising authority.
It refuses to act beyond the boundaries you set.

## Release Status

**v1.0.0-voice-core** (January 18, 2026) — Foundation-complete voice system

✓ Stateless voice mode with memory disabled  
✓ Audio streaming (Piper TTS, time-to-first-audio 500-900ms)  
✓ STOP interrupt (<50ms dominance guaranteed)  
✓ Push-to-Talk (Whisper + SPACEBAR)  
✓ State machine (SLEEP/LISTENING/THINKING/SPEAKING)  
✓ Option B burn-in validated (14/14 tests, 0 anomalies)

→ **[Release Notes](RELEASE_NOTES.md)** — Why this release matters  
→ **[Changelog](CHANGELOG.md)** — What was added, fixed, and why  
→ **[Foundation Lock](FOUNDATION_LOCK.md)** — What must never be broken  

## Core Principles

- **Local-first** — All intelligence, memory, and decisions stay on your hardware
- **Explicit confirmation** — Meaningful actions require deliberate approval
- **No silent execution** — Actions are visible before they occur
- **No background monitoring** — Listening and vision activate only on request
- **Manual control wins** — Physical overrides take priority at all times
- **Full auditability** — Every action is logged and reviewable
- **Zero anthropomorphism** — ARGO does not pretend to be sentient
- **Fail-closed behavior** — Uncertainty stops execution

## What ARGO Does (v1.0.0-voice-core)

### Currently Works

- **Voice-based interaction** via Push-to-Talk (SPACEBAR)
- **Audio transcription** with Whisper speech-to-text
- **Real-time audio synthesis** with Piper TTS
- **Stateless voice queries** (single-turn, no history injection)
- **Explicit STOP interrupt** (<50ms latency, always wins)
- **Sleep mode** (voice disabled, SPACEBAR only)
- **Environment persistence** (.env configuration auto-load)
- **Intent parsing** with LLM (no autonomous execution)

### Explicitly Does NOT Do (v1.0.0-voice-core)

- **Voice wake-word detection** (design complete, implementation pending)
- **Voice personality/identity** (uses generic Piper voice, deferred to Phase 7D)
- **Autonomous tool execution** (out of scope)
- **Background listening** (only on explicit SPACEBAR)
- **Multi-turn voice conversations** (voice mode is stateless-only)
- **Memory recall in voice mode** (disabled for hygiene)
- **Voice identity switching** (deferred to future release)

→ **[Design Documents](PHASE_7A3_WAKEWORD_DESIGN.md)** — Detailed wake-word architecture (design-only, no code yet)

## Control Guarantees

1. **State machine is authoritative** — No component bypasses state transitions
2. **STOP always interrupts** — <50ms latency, even during audio streaming
3. **Voice mode is stateless** — No prior conversation context injection
4. **SLEEP is absolute** — Voice commands ignored, SPACEBAR PTT only
5. **Prompt hygiene enforced** — System instruction prevents context leakage
6. **Audio streaming is non-blocking** — TTF-A reduced from 20-180s to 500-900ms

## How to Run

### Prerequisites

- Python 3.10+
- Whisper (speech-to-text)
- Piper TTS (text-to-speech)
- Sounddevice (audio playback)

### Voice Mode (Stateless)

```powershell
python wrapper/argo.py "your question here" --voice
```

Result: Single-turn question, memory disabled, <50ms STOP responsiveness.

### PTT Mode (Push-to-Talk)

```powershell
python wrapper/argo.py
# Then press SPACEBAR to activate Whisper transcription
# Speak your question
# ARGO responds
# Press SPACEBAR again to interrupt/stop at any time
```

### Interrupt/Stop

**Any state:** Press SPACEBAR, then speak "STOP" (or just hold SPACEBAR)  
**During audio playback:** STOP cancels in <50ms  
**During THINKING:** STOP cancels LLM call (pending input saved)  

### Sleep Mode

**Enter:** Say "sleep" (PTT mode)  
**Exit:** System reboot (wake-word not yet implemented)  
**Effect:** Voice disabled, SPACEBAR PTT available for manual control

## Architecture Overview

ARGO Core runs on your main PC and handles all intelligence, memory, and decision-making.
Raspberry Pi nodes act as sensory peripherals only.

They can see, hear, speak, and display.
They cannot decide, remember, or execute independently.

Authority exists in one place.
Peripherals have none.

→ See: [docs/README.md](docs/README.md) — Documentation index

## Project Status

**Foundation is locked.** No silent refactors allowed.  
**All future changes must be additive via PR.**

Completed phases:
- Phase 7B: State machine with deterministic transitions
- Phase 7B-2: Integration & hard STOP interrupt
- Phase 7B-3: Command parsing with safety gates
- Option B: Confidence burn-in (14/14 tests passed)
- Phase 7A-2: Audio streaming (TTFA 500-900ms)
- Phase 7A-3a: Wake-word design (paper-only, no code)

Intentionally deferred:
- Phase 7A-3: Wake-word implementation
- Phase 7D: Voice personality (Allen identity)
- Tool invocation (autonomous execution)
- Multi-turn voice conversations

## Quick Start

→ **[Getting Started](GETTING_STARTED.md)** — Installation and first run instructions

## Documentation

- **[Docs Index](docs/README.md)** — Master table of contents for all documentation
- **[Getting Started](GETTING_STARTED.md)** — Installation, setup, and first run
- **[Release Notes](RELEASE_NOTES.md)** — Why v1.0.0-voice-core matters
- **[Changelog](CHANGELOG.md)** — What was added, fixed, and deferred
- **[Foundation Lock](FOUNDATION_LOCK.md)** — Critical constraints that must never be broken
- [System Architecture](ARCHITECTURE.md) — Memory, preferences, and voice system design
- [Artifact Chain Architecture](docs/architecture/artifact-chain.md) — The three-layer artifact system (Transcription, Intent, Planning)
- [Frozen Layers](FROZEN_LAYERS.md) — Official freeze of v1.0.0-v1.3.0 safety chain
- [Master Feature List](docs/specs/master-feature-list.md) — Planned capabilities and scope boundaries
- [Raspberry Pi Architecture](docs/architecture/raspberry-pi-node.md) — Peripheral design and trust boundaries
- [Usage Guide](docs/usage/cli.md) — Interactive commands and examples
- [Phase 7A-3 Wake-Word Design](PHASE_7A3_WAKEWORD_DESIGN.md) — Architecture for future wake-word feature
- [Wake-Word Decision Matrix](WAKEWORD_DECISION_MATRIX.md) — Comprehensive trigger-outcome reference
- [Go/No-Go Checklist](PHASE_7A3_GONO_CHECKLIST.md) — Acceptance criteria before implementation

---

**Tommy Gunn — Creator & Architect**

GitHub: [@tommygunn212](https://github.com/tommygunn212)

January 2026 | Release v1.0.0-voice-core

## Licensing

ARGO is available under a dual-licensing model.

**Non-commercial use:** Free for personal, educational, and research use under the ARGO Non-Commercial License.  
**Commercial use:** Requires a separate commercial license agreement.

Commercial use includes any revenue-generating product, service, or internal business deployment.

See `LICENSE` for full terms.

## Performance & Latency

ARGO v1.5.1 includes comprehensive latency instrumentation plus audio control:

- **8 checkpoint measurements** track timing at every stage (input → transcription → intent → execution)
- **3 latency profiles** (FAST ≤6s, ARGO ≤10s, VOICE ≤15s) enforce response time budgets
- **Zero mystery delays** — all delays intentional, measured, and logged
- **Async-safe delays** — no blocking sleeps, compatible with streaming responses
- **Regression tests** — 18 tests enforce FAST mode contract and prevent regressions

### Audio Control & State Machine

ARGO v1.5.1 includes deterministic state machine for wake/sleep/stop control:

- **4 states**: SLEEP, LISTENING, THINKING, SPEAKING
- **3 commands**: "ARGO" (wake), "go to sleep" (sleep), "stop" (stop audio)
- **9 allowed transitions** — deterministic, no NLP, no personality
- **Full control**: Instant stop with <50ms latency
- **31 comprehensive tests** — all state transitions validated

For detailed documentation:
- [LATENCY_INTEGRATION_COMPLETE.md](LATENCY_INTEGRATION_COMPLETE.md) — Latency framework
- [LATENCY_SYSTEM_ARCHITECTURE.md](LATENCY_SYSTEM_ARCHITECTURE.md) — Technical architecture
- [PHASE_7B_COMPLETE.md](PHASE_7B_COMPLETE.md) — State machine design and testing

**Status**: Framework integrated and tested. Ready for wrapper integration.

## Project Milestones

ARGO development is tracked in phases. See [MILESTONES.md](MILESTONES.md) for:
- ✅ Completed features (Memory, Transcription, Intent Parsing, Latency Framework, State Machine)
- 🚧 Current development status (State Machine Integration)
- 📋 Planned features (FastAPI Audio Streaming, Wrapper Integration)
- 📊 Project metrics and design principles

**Current Status:** v1.5.1 (State Machine + Audio Control) — Framework Ready

For commercial licensing inquiries, contact the project owner via GitHub.
