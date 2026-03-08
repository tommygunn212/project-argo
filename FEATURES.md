# FEATURES.md

## ARGO Neural Network: Feature Roadmap and Capabilities

This document tracks all current and planned features for ARGO, the neural network command diagnostic system. It is canonical and should be referenced for all self-knowledge and deterministic responses about ARGO's capabilities.


### Current Features (Mar 2026)
- Always-listening VAD pipeline
- Whisper STT integration
- Ollama LLM (neural network) for response generation
- Piper TTS for audio output
- **OpenAI Cloud STT** (`gpt-4o-mini-transcribe`) — fast cloud transcription with prompt support
- **OpenAI Cloud TTS** (`gpt-4o-mini-tts`) — low-latency streaming synthesis with 13 voices and `instructions` parameter
- **Multi-engine STT switching**: OpenAI Cloud, Azure, Faster Whisper, OpenAI Whisper — selectable at runtime
- **Multi-engine TTS switching**: OpenAI TTS, Edge TTS, Azure Neural — selectable at runtime
- **Frontend V2** (`/v2`): Full-featured cyberpunk UI with 6 tabs (Dashboard, Chat, Voice, Home, Tools, System)
- **14 gate tuning sliders**: Real-time adjustment of VAD, barge-in, confidence, token, and verbosity gates
- **Engine configuration panel**: Switch STT/TTS engine, model, and voice from the UI
- Deterministic system health and hardware queries
- Local music index and deterministic music resolution
- OpenRGB lighting control (optional)
- State machine enforcement for all transitions
- Barge-in and audio ownership logic (overhauled — both engines, buffer clearing, suppression guards)
- Timeline event capture for replay/debug
- Structured session and memory management
- Canonical law and 5 Gates enforcement
- Frontend text input (bypass STT, type commands directly)
- Self-diagnostics: ARGO checks its own components (Ollama, Piper, Whisper, audio)
- Assisted recovery: Proposes fixes and executes only with user approval
- Security hardened: localhost-only binding, no secrets in source, SQL injection prevention
- Pinned dependencies for reproducible installs

#### Codebase Statistics (Jan 2026)
- Approximate total Python lines of code: 3,701,021
- Equivalent to roughly 74,020 printed pages (at 50 lines per page)

### Planned Features (2026+)
- RAG (Retrieval-Augmented Generation) for self-documentation and deterministic recall
- SQL/Database integration for structured data queries
- Advanced session memory and context-aware responses
- Plugin/extension system for third-party integrations
- Multi-user session support
- Enhanced UI/UX for debugging and control
- Full audit logging and compliance features
- More deterministic system health and diagnostics
- Expanded music/media control
- Additional language and TTS/STT options
- ...and over 200 more features in the roadmap

### Terminology
- ARGO is always referred to as a "neural network" (not "AI").
- All user-facing documentation and responses must use "neural network" terminology.

---

This file is canonical. All ARGO self-knowledge and feature queries should be answered deterministically from this document.
