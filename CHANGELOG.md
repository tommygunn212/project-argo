# Changelog

## v1.6.12 — Session Context Always-On for Questions (2026-02-03)

### Changed
- **All questions now use session context**: If the conversation buffer has content, it's always passed to the LLM
- **Removed fragile pronoun detection**: No longer guessing whether user needs context based on specific words
- **Simpler logic**: `buffer.size() > 0` → use buffered mode for questions

### Rationale
- Pronoun-based detection was missing too many follow-up patterns ("what about the wings?", "why?", "and the beak?")
- Buffer is already bounded to 3 turns (Phase 5), so always including it is safe
- Better to give LLM context it might not need than to miss obvious follow-ups

---

## v1.6.11 — Session Context Pronoun Fix (2026-02-03)

### Fixed
- **"Tell me about their feet" now uses session context**: Possessive pronouns (`their`, `theirs`, `his`, `hers`) now trigger buffered context mode
- **Follow-up questions work**: Session memory is correctly passed to LLM when pronoun references are detected
- **Expanded pronoun detection**: Added `he`, `she`, `him`, `her`, `his`, `hers`, `their`, `theirs`, `about them`, `about their`, `about those`

### Root Cause
- Pronoun detection list was missing possessive pronouns like "their"
- `context_scope=isolated` was being used instead of `context_scope=buffered` for follow-up questions

---

## v1.6.10 — Phase 5: Bounded Session Continuity (2026-02-03)

### Added
- **Session memory (bounded, ephemeral)**: Conversation buffer now constrained to 3-turn session window
- **Turn limit enforcement**: Auto-clears after 3 conversation exchanges to prevent unbounded context growth
- **Command bypass**: ACTION intents clear session context (commands ignore conversation history)
- **STOP clears context**: "stop", "pause", "cancel" keywords reset session immediately
- **Error clears context**: Clarification/error responses reset session state
- **Toggle support**: `session_memory_enabled` runtime override for one-click disable

### Changed
- `ConversationBuffer` now tracks session turn count with `SESSION_TURN_LIMIT = 3`
- Buffer logs: `[SESSION] Context appended (turn 2/3)`, `[SESSION] Context cleared: STOP`
- Clarification responses now clear session context (error-like state)

### Architecture
- Phase 5 wraps and disciplines existing `convo_buffer` — no new abstraction layer
- Clear triggers: STOP, command, error, turn limit, toggle OFF, restart
- Session context never affects: intent classification, command execution, system health

---

## v1.6.9 — Implicit Memory Writes (2026-02-03)

### Fixed
- **"My name is Tommy" now works**: Direct identity statements no longer hit NON_PROPOSITIONAL_GUARD
- **No confirmation needed**: Implicit statements ("My name is X", "Call me X") store immediately with natural acknowledgment ("Got it, Tommy.")

### Added
- **Implicit memory write detection**: Recognizes "My name is X" and "Call me X" without requiring "remember that"
- **Identity pattern bypass**: Non-propositional guard now passes through personal statements (my name, I like, I prefer, etc.)
- **Natural acknowledgment**: Implicit writes respond with "Got it, {name}." instead of asking for confirmation

### Changed
- `_parse_memory_write()` now handles implicit identity statements
- `_is_non_propositional_utterance()` bypasses guard for identity patterns

---

## v1.6.8 — Barge-In Echo Suppression (2026-02-03)

### Fixed
- **Barge-in echo cancellation**: Short deterministic responses (time queries, system status) now suppress barge-in for 2 seconds
- **World time cut-off**: "What time is it in London?" no longer gets interrupted by Argo's own voice echoing into the mic
- **Local time cut-off**: "What time is it?" also protected from echo-triggered barge-in

### Added
- `is_interrupt_suppressed()` method on TTS sinks to check suppress window
- `is_barge_in_suppressed()` method on pipeline for main loop to query
- `suppress_barge_in_seconds` parameter now wired through to world time and local time handlers

---

## v1.6.7 — Personality Transform Layer (Phase 4) (2025-02-03)

### Added
- **Personality as pure transform layer**: Personality shaping applied AFTER facts, BEFORE output — never touches intent, execution, or memory
- **4 predefined profiles**: tommy_gunn (sharp, 4 sentences), jarvis (calm, 3), rick (chaotic, 5), plain (flat, 2)
- **Intent-based gating**: NONE (system health), MINIMAL (actions), FULL (questions), NEUTRAL (errors)
- **Session toggle**: `get_personality_state().toggle(False)` for one-click disable
- **Profile switching**: `get_personality_state().set_profile('jarvis')` at runtime

### Enforced
- **Max sentence caps**: Each profile limits response length (2-5 sentences max)
- **Follow-up stripping**: "How can I help?", "Let me know if...", etc. automatically removed
- **Forbidden pattern removal**: "As an AI...", "I apologize..." stripped from output

### Architecture
- `PersonalityProfile` dataclass with tone, verbosity, humor_level, max_sentences, forbidden_patterns
- `PersonalityFormatter` class with format(), sentence cap, forbidden/follow-up stripping
- `PersonalityGate` enum (NONE, MINIMAL, FULL, NEUTRAL) mapped to IntentTypes
- Pipeline integration: Applied after `_strip_disallowed_phrases()`, before TTS

---

## v1.6.6 — Volume Control + Hardware Info + LLM Confidence (2025-02-03)

### Fixed
- **System volume control**: Updated pycaw API usage (`.EndpointVolume` property instead of deprecated `.Activate()`)
- **Volume command patterns**: "volume 50%", "lower volume", "louder", "quieter" now recognized
- **SQL parameter binding**: Fixed era-based music queries ("play 80s music") parameter order mismatch
- **Imperative verb guard**: "give me three numbers" now passes to LLM instead of hitting ISOLATED_SHORT_GUARD

### Added
- **Hardware identification**: "What kind of CPU/GPU/motherboard do I have?" now returns actual hardware info via WMI
- **Pronoun context detection**: Questions with "it", "they", "this" now include conversation buffer for context
- **Expanded query patterns**: More natural phrasing for CPU, motherboard, volume queries

### Improved
- **LLM confidence**: Prompts now instruct "If you don't know, say so briefly" — no speculation or hedging
- **No prompt leakage**: LLM won't describe its own configuration/mode in responses

---

## v1.6.5 — Conversational Presence (2025-02-03)

- **Response style gating**: DRY (minimal/"Done."), NEUTRAL, SNARK modes based on intent type
- **Action risk classification**: REVERSIBLE actions execute immediately, DESTRUCTIVE actions prompt confirmation
- **Smarter clarification**: Context-aware prompts ("Notepad or browser?") instead of generic rephrasing requests
- **Minimal acknowledgments**: Silent success path for reversible actions; terse responses for routine tasks
- Added `ResponseStyle` and `ActionRisk` enums to config.py
- Added helper methods: `_get_response_style`, `_get_action_risk`, `_minimal_ack`, `_get_clarification_prompt`
- MEMORY_MIN_CONFIDENCE threshold (0.20) defined for future memory persistence filtering

---

## v1.6.4 — Audio Responsiveness + World Time (2025-02-03)

- **World Time**: "What time is it in Tokyo/London/etc?" now handled deterministically with accurate timezone lookup (100+ cities/countries supported)
- **Imperative passthrough**: Sentences starting with action verbs (give, tell, show, list, etc.) now pass to LLM instead of being rejected as unclear
- TTS pre-roll reduced from 100ms to 50ms (faster first-word playback)
- Inter-sentence gap reduced from max 50ms to max 20ms (continuous-sounding responses)
- PERSONAL_MODE_MIN_CONFIDENCE loosened from 0.25 to 0.15 (fewer rejection moments)
- Audio normalization skipped when peak >= 0.85 (micro-latency win)

---

## v1.6.3 — Latency Tuning for Personal Use (2025-02-03)

- STT beam_size reduced from 5 to 1 (faster transcription, ~200-500ms savings)
- Silence detection threshold reduced from 1.5s to 0.8s (faster response after speech ends)
- VAD minimum voiced duration reduced from 300ms to 180ms (accepts shorter commands)

---

## v1.6.2 — Natural Language Flexibility (2025-02-03)

- Improved natural language handling for counting and app control.

---

## v1.6.1 — Deterministic Core Stabilization (2025-02-02)

### Added
- Canonical / deterministic commands now bypass STT confidence gates entirely
- Unresolved noun phrase detection triggers clarification instead of LLM fallback
- Six missing method stubs added to pipeline.py for interrogative detection and clarification flow
- VAD_END minimum voiced speech threshold set to 300ms (reduces false triggers from grunts/noise)
- Natural language phrasing support: COUNT ("let's count to 5", "give me 3 numbers"), SYSTEM HEALTH ("how's my computer doing", "anything wrong with my system"), APP CONTROL ("shut notepad", "close the browser")

### Fixed
- Type annotations corrected across pipeline.py (Optional[str] for nullable returns)
- focus_app → focus_app_deterministic consistency
- Guarded None values for add_memory, play_by_genre, play_by_keyword
- Unbound variable guards for all edge cases in pipeline execution
- Test harness safety: removed import-time sys.exit() from 4 test files
- bare except: clauses replaced with logged exceptions throughout codebase

### Known Issues (Not Blocking)
- 12 pre-existing test failures (test debt) — tracked in TEST_DEBT.md
- test_stt_hardening.py: outdated function signature
- test_clarification_gate.py: assertion mismatch
- test_confirmable_identity_memory.py: harness issues
- test_piper_integration.py: env configuration
- test_coordinator_v1/v2: integration test issues

---

## v1.6.0 — Voice Stability & UX Refinement (Stable)

### Core Stability
- Fixed pipeline state machine to allow THINKING → LISTENING
- Prevents illegal transitions when TTS is suppressed
- Eliminates state-machine warnings and deadlocks
- Deterministic behavior confirmed via logs
- Barge-in handling fully stabilized
- Forced audio release during TTS works correctly
- Clean recovery to LISTENING with no duplicate transitions

### Audio + Interaction Flow
- TTS suppression paths now terminate cleanly
- Silence and low-confidence exits no longer poison pipeline state
- Interaction lifecycle consistently reaches INTERACTION_END

### Intent + UX Improvements
- Canonical routing refined to prevent misclassification
- Identity questions no longer misrouted as SYSTEM_HEALTH
- Keyword-only canonical bypass reduced
- MUSIC intent handling improved:
	- Confidence guards scoped by intent (music commands more tolerant)
	- Prevents false rejections for short, common commands
	- MUSIC intent no longer falls back to open-ended LLM responses
	- Failed matches now request clarification instead of hallucinating

### Safety & Governance
- No changes to gate system (validation, permission, safety, resource, audit)
- No loosening of security or execution constraints
- Behavior improvements are scoped and deterministic

## v1.5.0 – Hardened Core Baseline
- Deterministic system health + disk queries (no LLM)
- Conversational system status formatting (voice-friendly)
- Expanded hardware specs (CPU, memory, GPU, board, BIOS)
- Local music index (data/music_index.json) + rebuild script
- Music hardening and stricter matching for playback
- OpenRGB lighting control via deterministic commands
- Audio device selection via config.json
- Atomic persistence for memory and prefs
- TOCTOU execution guards
- Async orchestration and TTS worker thread
- Stabilized runtime core

## v1.0.0 – Initial Public Release
- Voice-first local AI assistant
- Wake word detection, STT, LLM, TTS pipeline
