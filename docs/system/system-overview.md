# System Overview

This document describes what Project Argo is, what makes it different, and what it is designed to enable.

## What Argo Is

Argo is a **locally controlled conversational system** that prioritizes speed, determinism, and inspectable decision-making.

It provides:
- Direct control over conversation flow (no hidden memory, no silent refusals)
- Fast, persistent model inference via Ollama
- Explicit policies for replay, context filtering, and confidence control
- Complete diagnostic logging of every decision
- A foundation for progressive relaxation of constraints under user control

Argo is not a chatbot. It is a tool for building and understanding AI-assisted workflows.

## What Makes Argo Different

**No Hidden Memory**
- Replay is explicit and visible: `--replay last:5` or `--replay session`
- Sessions must be named: `--session work` to persist across runs
- No automatic context accumulation
- Every interaction logged for audit and debugging

**No Silent Refusals**
- All decisions are logged with reasoning
- Filtering policies are transparent (what types are included/excluded)
- Budget enforcement is visible (chars_used, trimmed, entries_filtered)
- Confidence levels are injected directly into prompts

**No Cloud Safety Layers**
- Model runs locally on your hardware
- No external filtering, no content moderation
- No third-party tracking or telemetry
- Full sovereignty over what prompts the model sees

**Explicit Replay, Confidence, and Filtering Policies**
- REPLAY_FILTERS: Deterministic mapping of reason → entry types to include
- Context Strength: Classification based on context quality (strong/moderate/weak)
- Confidence Instructions: Behavior guidance injected by strength
- All configurable without code changes

**Full Diagnostic Logging**
- Every interaction recorded as JSON (one line per turn)
- Replay decisions logged: what was filtered, why, how confident
- Budget impact tracked: entries available, entries used, trimming flag
- Enables failure analysis, pattern discovery, and iterative refinement

## What Argo Is Designed to Enable

**Progressive relaxation of constraints under user control, enabling full local sovereignty without loss of reliability.**

Today, Argo enforces strict governance:
- Replay is filtered by reason
- Context strength limits confidence
- Sessions require explicit naming
- Intent classification gates certain inputs

This foundation allows you to:
- Understand why each constraint exists
- Measure the impact of relaxing constraints
- Build confidence in the system's behavior
- Eventually enable full autonomy for specific use cases

The goal is not a "smarter" AI. It is an **understandable** AI that you trust because you can inspect its reasoning.

## Key Documents

- **[ARCHITECTURE.md](../../ARCHITECTURE.md)**: Detailed explanation of systems, pipelines, and design rationale
- **[CODE_REFERENCE.md](../../CODE_REFERENCE.md)**: Function reference and codebase map
- **[README.md](../../README.md)**: Quick start and usage examples