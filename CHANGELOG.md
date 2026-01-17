# Changelog

All notable changes to Argo are documented here.

## [0.9.0] – 2026-01-17

### Added
- Deterministic recall mode for meta-queries ("what did we talk about?")
- Conversation browsing (list, show by date/topic, summarize, open)
- User preference detection and persistence (tone, verbosity, humor, structure)
- Memory hygiene enforcement (recall queries never stored)
- Voice validation safety net (traction control model)
- Interactive CLI mode with natural conversation flow
- PowerShell alias integration (`ai` command)

### Core Systems
- TF-IDF memory retrieval with topic fallback (Phase 2a)
- Three-tier memory fallback (TF-IDF → Topic → Recency)
- Preferences auto-detection via pattern matching
- Mode detection (recall vs generation)
- Explicit intent-based routing (no auto-detection)

### Design
- Safety-first validator (not a style cop)
- Read-only conversation browsing (no modification)
- Memory factual summary only (no interpretation)
- Human control over all inference

### Initial Release
First stable release with memory, preferences, recall, and browsing fully integrated and tested.
