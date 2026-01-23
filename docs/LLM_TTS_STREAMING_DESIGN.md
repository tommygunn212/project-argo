# LLM → TTS Streaming (Design Note, Future Feature)

**Status:** Design-only (do not implement yet).

## Goal
Enable optional sentence-level streaming from LLM output into TTS so responses begin speaking earlier **without** changing default behavior.

## Constraints
- **Feature-flagged only** (off by default).
- **No default behavior changes.**
- **No new threads, no new buffering logic.**
- **No audio path refactors.**

## Proposed Flow (Sentence-Level)
1. LLM uses streaming output (Ollama `stream=True`).
2. Collect tokens into a buffer.
3. When a **complete sentence** is detected, enqueue that sentence to TTS.
4. Continue until stream ends, then flush any trailing sentence fragment.

## Sentence Boundary Rules (Draft)
- Prefer clear punctuation: `.`, `!`, `?` followed by a space.
- Avoid splitting on abbreviations (e.g., "e.g.", "Dr.").
- Do **not** enqueue mid-sentence fragments.

## Feature Flag (Draft)
- `LLM_TTS_STREAMING=false` by default.
- When `true`, enable sentence-level streaming behavior.

## Out of Scope (Do Not Implement)
- VAD integration
- Buffering optimizations
- Coordinator flow changes
- Memory logic changes
- Raspberry Pi concerns
- Packaging

## Rationale
This design preserves current stability while enabling future, optional streaming that improves perceived latency.
