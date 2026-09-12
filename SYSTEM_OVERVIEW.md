# SYSTEM_OVERVIEW.md

## ARGO Neural Network: System Overview

ARGO is a deterministic, local-first neural network command diagnostic system. It is designed for predictability, debuggability, and user control. This document provides a canonical overview of ARGO’s architecture, operational layers, and guiding principles as of v1.9.1 (2026-09-12).

### Architecture
- Two voice paths: smooth Browser → LiveKit → OpenAI Realtime, and classic VAD → STT → LLM router → TTS
- Classic path uses bounded capture, selected-device output ownership, streaming resampling, sentence prefetch, and explicit failure cleanup
- LLM routing supports OpenAI, Ollama, and Gemini through a single config-driven interface with a deterministic fallback chain
- Deterministic memory and session management, with SQLite default and optional PostgreSQL durable memory backend
- Canonical law and 5 Gates enforcement

### Key Principles
- Deterministic responses for all self-knowledge and system queries
- No generative synthesis for ARGO’s own architecture or features—always return canonical documentation
- All user-facing references use "neural network" (never "AI")
- All operational gates (5 Gates of Hell) are strictly enforced

### RAG (Retrieval-Augmented Generation)
- Documentation and self-knowledge can be retrieved with bounded optional context lookup
- All responses about ARGO’s internals are sourced from canonical files (ARCHITECTURE.md, FEATURES.md, DATABASE.md, SYSTEM_OVERVIEW.md)

---

This file is canonical. All ARGO self-knowledge and system overview queries should be answered deterministically from this document.
