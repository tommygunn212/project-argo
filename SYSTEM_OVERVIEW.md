# SYSTEM_OVERVIEW.md

## ARGO Neural Network: System Overview

ARGO is a deterministic, local-first neural network command diagnostic system. It is designed for predictability, debuggability, and user control. This document provides a canonical overview of ARGO’s architecture, operational layers, and guiding principles.

### Architecture
- 7-layer voice pipeline: InputTrigger, SpeechToText, IntentParser, ResponseGenerator, OutputSink, StateMachine, UI/Debugger
- Always-listening VAD loop with explicit state machine enforcement
- Deterministic memory and session management
- Canonical law and 5 Gates enforcement

### Key Principles
- Deterministic responses for all self-knowledge and system queries
- No generative synthesis for ARGO’s own architecture or features—always return canonical documentation
- All user-facing references use "neural network" (never "AI")
- All operational gates (5 Gates of Hell) are strictly enforced

### RAG (Retrieval-Augmented Generation)
- Documentation and self-knowledge are indexed for deterministic retrieval
- All responses about ARGO’s internals are sourced from canonical files (ARCHITECTURE.md, FEATURES.md, DATABASE.md, SYSTEM_OVERVIEW.md)

---

This file is canonical. All ARGO self-knowledge and system overview queries should be answered deterministically from this document.
