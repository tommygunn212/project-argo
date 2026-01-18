# Documentation Index

This folder contains specifications, architectural decisions, and implementation guides for ARGO.

**Note:** All documentation and code in this repository are covered by the repository's licensing terms. The ARGO Non-Commercial License applies to all specifications, designs, and implementation guides. Commercial use of any material in these docs requires a separate commercial license agreement.

---

## Getting Started

**[← GETTING_STARTED.md](../GETTING_STARTED.md)** — Installation, setup, and first run instructions

Start here if you're new to ARGO. Covers:
- System requirements (Python, Ollama, Windows)
- Step-by-step setup via `setup.ps1` or manual installation
- Running ARGO CLI and web interface
- Test suite verification
- Troubleshooting common issues

---

## intent/

**artifacts.md** — Complete guide to ARGO's Intent Artifact system. Covers deterministic intent parsing without execution, confirmation gates, supported verb grammar, ambiguity preservation, and the clean pipeline from transcription through future execution.

Use this to:
- Understand how text becomes structured intent
- Learn why execution is explicitly excluded
- Design future Executable Intent and Execution layers
- Understand confirmation gates
- Debug intent parsing issues

## transcription/

**whisper.md** — Complete guide to ARGO's Whisper audio transcription module. Covers the transcription-only design philosophy, input/output contracts, confirmation gate flow, failure handling, and logging/auditability.

Use this to:
- Understand how ARGO transcribes audio
- Learn the confirmation gate design
- Understand what Whisper explicitly does NOT do (intent detection, command execution, background listening)
- Set up transcription in your ARGO instance
- Debug transcription issues

## specs/

**master-feature-list.md** — The canonical scope document. Lists all 200 planned capabilities, grouped by domain (voice, lighting, climate, media, automation, security, etc.). Also defines explicit non-behaviors (what ARGO refuses to do).

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

*Architectural Decision Records (ADRs)*

Records of significant design choices and why they were made.

---

## Quick Navigation

**First time reading ARGO?** Start with the main [README.md](../README.md).

**Want to understand the architecture?** Read [system/architecture.md](system/architecture.md) for Core system, then [architecture/raspberry-pi-node.md](architecture/raspberry-pi-node.md) for distributed design.

**Need complete scope?** See [specs/master-feature-list.md](specs/master-feature-list.md).

**Implementing a new feature?** Check the feature list, then understand the domain architecture in the relevant system docs.

**Debugging a system?** Audit the logs in `logs/` and review memory in `memory/` for behavior verification.