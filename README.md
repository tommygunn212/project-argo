# ARGO (Autonomous-Resistant Governed Operator)

ARGO is a local-first AI control system designed to act only when explicitly instructed. It runs on your main PC and uses Raspberry Pi nodes as sensory peripherals, but all decisions, memory, and authority remain on the core system.

ARGO does not guess intent. It does not execute silently. It does not pretend to be something it is not. Every action requires explicit confirmation or follows a clear rule you have set. Every action is auditable. Every action respects your manual controls—if you override ARGO with a physical switch or button, ARGO backs off immediately.

The system is built on a single principle: **you remain in control**. ARGO is a tool that amplifies your voice, not a system that makes decisions on your behalf. It can assist with smart home automation, document editing, system monitoring, and conversational tasks, but it operates within explicit boundaries and refuses to exceed them.

ARGO stores memories of your preferences and prior interactions, but only when you ask it to. It can browse conversations you have had with it, but it cannot modify, delete, or hide them from you. It remembers what you tell it to remember and nothing else.

The codebase is intentionally simple. The system is auditable. The memory model is transparent. The voice system is deterministic. You can read the code, understand the flow, and verify the behavior. This is local-first software designed for trust, not convenience.

ARGO is not complete. Not all 200 planned capabilities are implemented. This repository represents the foundation: memory, preferences, recall mode, and conversation browsing. Future work will add home automation, media control, document assistance, and system monitoring—but only following the same principles of explicit permission, auditability, and manual override.

## Core Principles

- **Local-first operation** — All intelligence, memory, and decisions stay on your hardware
- **Explicit confirmation** — Actions that matter require deliberate approval
- **No silent execution** — You see what ARGO is about to do before it happens
- **No background monitoring** — ARGO listens and watches only when you activate it
- **Manual control always wins** — Physical switches and buttons override ARGO instantly
- **Full auditability** — Every decision is logged and reviewable
- **Zero anthropomorphism** — ARGO does not pretend to be sentient or have feelings
- **Fail-closed behavior** — Uncertainty means ARGO stops and reports the problem

## What ARGO Can Do

**Voice and Interaction**
Conversational AI with memory of your preferences and prior exchanges. Can recall what you discussed previously. Responds in a warm, confident tone while staying local to your PC.

**Conversation Browsing**
Review past interactions by date, topic, or keyword. Search conversation history without modification. Understand what ARGO learned about your preferences.

**Memory and Preferences**
Explicit storage of user preferences (tone, verbosity, humor style, structure). Automatic detection of patterns in how you interact. No background learning—changes only happen on request.

**Smart Home Foundations**
Room-aware voice control (via Raspberry Pi nodes as peripherals). Lighting, climate, and media control ready for integration. All decision logic remains on the core system.

**Document and Email Assistance**
Dictation support for Word and email composition. Rewriting and summarization of existing text. Never modifies or sends without explicit confirmation.

**System Monitoring**
CPU, GPU, disk, network, and printer status reporting. Health checks for connected sensors and devices.

## Architecture Overview

ARGO Core runs on your main PC and handles all intelligence, memory, and decision-making. Raspberry Pi nodes act as sensory peripherals—they capture audio and video, display content, control lights and TVs, and output speech, but they have no authority, no memory, and no independent logic. All Pis report back to Core for decisions.

This design keeps trust simple: one place where authority lives, zero ability for peripherals to act autonomously, and clear audit trails for every action.

→ See: [docs/architecture/raspberry-pi-node.md](docs/architecture/raspberry-pi-node.md) for how the distributed system works.

## Documentation

- **[Master Feature List](docs/specs/master-feature-list.md)** — All 200 planned capabilities, implementation status, and scope boundaries
- **[Raspberry Pi Architecture](docs/architecture/raspberry-pi-node.md)** — How the sensory nodes integrate with the core system
- **[System Architecture](ARCHITECTURE.md)** — Memory, preferences, recall mode, and voice system design
- **[Docs Index](docs/README.md)** — Where to find specs, philosophy, and usage guides

---

**Tommy Gunn — Creator & Architect**

GitHub: [@tommygunn212](https://github.com/tommygunn212)

December 2025

### Conversation browsing
```powershell
ai
argo > list conversations
argo > show topic eggs
argo > summarize eggs
argo > exit
```

## Exiting

Type `exit` or `quit` in interactive mode. Single-shot mode exits automatically.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design, data flow, and design principles.

## License

MIT
