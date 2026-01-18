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

## Core Principles

- **Local-first** — All intelligence, memory, and decisions stay on your hardware
- **Explicit confirmation** — Meaningful actions require deliberate approval
- **No silent execution** — Actions are visible before they occur
- **No background monitoring** — Listening and vision activate only on request
- **Manual control wins** — Physical overrides take priority at all times
- **Full auditability** — Every action is logged and reviewable
- **Zero anthropomorphism** — ARGO does not pretend to be sentient
- **Fail-closed behavior** — Uncertainty stops execution

## What ARGO Can Do

- **Voice-based interaction** with preference-aware responses
- **Audio transcription** with explicit user confirmation (Whisper)
- **Intent parsing** from confirmed text (deterministic, no execution)
- **Conversation browsing and recall** (deterministic, no model re-inference)
- **Explicit memory storage** and preference management
- **Smart home control foundations** (via Raspberry Pi peripherals)
- **Document and email drafting** with confirmation gates
- **Local system monitoring** and health reporting

## Architecture Overview

ARGO Core runs on your main PC and handles all intelligence, memory, and decision-making.
Raspberry Pi nodes act as sensory peripherals only.

They can see, hear, speak, and display.
They cannot decide, remember, or execute independently.

Authority exists in one place.
Peripherals have none.

→ See: [docs/architecture/raspberry-pi-node.md](docs/architecture/raspberry-pi-node.md)

## Project Status

ARGO is not feature-complete.
Not all 200 planned capabilities are implemented.

This repository represents the foundation: memory, preferences, recall mode,
and conversation browsing. New capabilities will be added only if they preserve
explicit permission, auditability, and manual override.

## Quick Start

→ **[Getting Started](GETTING_STARTED.md)** — Installation and first run instructions

## Documentation

- [Getting Started](GETTING_STARTED.md) — Installation, setup, and first run
- [System Architecture](ARCHITECTURE.md) — Memory, preferences, and voice system design
- [Artifact Chain Architecture](docs/architecture/artifact-chain.md) — The three-layer artifact system (Transcription, Intent, Planning)
- [Frozen Layers](FROZEN_LAYERS.md) — Official freeze of v1.0.0-v1.3.0 safety chain
- [Master Feature List](docs/specs/master-feature-list.md) — Planned capabilities and scope boundaries
- [Raspberry Pi Architecture](docs/architecture/raspberry-pi-node.md) — Peripheral design and trust boundaries
- [Docs Index](docs/README.md) — Specs, philosophy, and usage guides
- [Usage Guide](docs/usage/cli.md) — Interactive commands and examples

---

**Tommy Gunn — Creator & Architect**

GitHub: [@tommygunn212](https://github.com/tommygunn212)

December 2025

## Licensing

ARGO is available under a dual-licensing model.

**Non-commercial use:** Free for personal, educational, and research use under the ARGO Non-Commercial License.  
**Commercial use:** Requires a separate commercial license agreement.

Commercial use includes any revenue-generating product, service, or internal business deployment.

See `LICENSE` for full terms.

## Performance & Latency

ARGO v1.4.5 includes comprehensive latency instrumentation:

- **8 checkpoint measurements** track timing at every stage (input → transcription → intent → execution)
- **3 latency profiles** (FAST ≤6s, ARGO ≤10s, VOICE ≤15s) enforce response time budgets
- **Zero mystery delays** — all delays intentional, measured, and logged
- **Async-safe delays** — no blocking sleeps, compatible with streaming responses
- **Regression tests** — 18 tests enforce FAST mode contract and prevent regressions

For detailed documentation:
- [LATENCY_INTEGRATION_COMPLETE.md](LATENCY_INTEGRATION_COMPLETE.md) — Integration summary
- [LATENCY_SYSTEM_ARCHITECTURE.md](LATENCY_SYSTEM_ARCHITECTURE.md) — Technical architecture
- [BASELINE_MEASUREMENT_QUICK_START.md](BASELINE_MEASUREMENT_QUICK_START.md) — How to measure

**Status**: Framework integrated and tested. Ready for baseline measurement collection.

## Project Milestones

ARGO development is tracked in phases. See [MILESTONES.md](MILESTONES.md) for:
- ✅ Completed features (Memory, Transcription, Intent Parsing, Latency Framework)
- 🚧 Current development status
- 📋 Planned features (Baseline Measurement, Performance Optimization)
- 📊 Project metrics and design principles

**Current Status:** v1.4.5 (Latency Instrumentation Foundation) — Framework Ready

For commercial licensing inquiries, contact the project owner via GitHub.
