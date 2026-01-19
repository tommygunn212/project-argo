# FOUNDATION LOCK — Critical Constraints for ARGO v1.0.0-voice-core

**Date:** January 18, 2026  
**Status:** LOCKED - All future releases must maintain these constraints  
**Audience:** All developers, reviewers, and future maintainers

This document explicitly states what must NEVER be broken. If you are modifying ARGO code, read this first.

---

## Executive Summary

ARGO's foundation consists of 6 non-negotiable guarantees. These are not suggestions. They are architectural facts enforced by design.

| Guarantee | Constraint | Why |
|-----------|-----------|-----|
| 1. State Machine Authority | No component bypasses state machine | Ensures predictable, auditable control flow |
| 2. STOP Dominance | STOP interrupts in <50ms always | User manual override must work immediately |
| 3. Voice Statelessness | Voice mode injects zero history | Prevents sensitive context leakage |
| 4. SLEEP Absoluteness | SLEEP disables all voice input | System must be able to become unlistening |
| 5. Prompt Hygiene | System instruction prevents context bleed | Even with bugs, prompt structure is defensible |
| 6. Streaming Non-Blocking | Audio doesn't block user control | UI remains responsive during long synthesis |

**If any guarantee is broken, that release CANNOT ship.**

---

## 1. STATE MACHINE IS AUTHORITATIVE

### The Constraint

The state machine (SLEEP/LISTENING/THINKING/SPEAKING) is the single source of truth for system control flow.

**No component may:**
- Bypass state transitions
- Operate outside the current state
- Override state constraints
- Create new states
- Permit state transitions that are not explicitly defined

### The Current States

```
SLEEP → LISTENING (via reboot or manual intervention)
        ↓
LISTENING → THINKING (PTT or future wake-word request)
        ↓
THINKING → SPEAKING (LLM has response)
        ↓
SPEAKING → LISTENING (response finished or STOP received)

STOP can interrupt from any state, returns to LISTENING
```

### What This Means for Code

**Allowed:**
- Adding new command types (if they respect state guards)
- Adding event logging (additive, doesn't change state logic)
- Optimizing state machine internals (if behavior unchanged)
- New listeners that call state machine (if respecting authority)

**Not Allowed:**
- Removing SLEEP→LISTENING gate
- Adding direct LISTENING→SPEAKING transition (must go through THINKING)
- Creating wake-word that forces state changes
- Disabling state machine checks for "performance"
- Permitting operations outside current state

### Testing Requirement

Any PR modifying state machine must include:
- Test: Verify all valid transitions work
- Test: Verify all invalid transitions are blocked
- Test: Verify STOP returns from any state to LISTENING

---

## 2. STOP ALWAYS INTERRUPTS (< 50ms Latency)

### The Constraint

STOP is the user's manual override. It must interrupt any operation with latency <50ms, guaranteed.

This is measured from:
- Command parser receives "STOP"
- To: System returns to LISTENING state
- Including: Piper process kill, LLM call cancellation, audio buffer clearing

### What STOP Must Do

1. **Kill Piper TTS immediately** — <10ms
   - Piper process terminated
   - Any pending audio output cancelled
   - Audio buffer cleared

2. **Cancel LLM calls** — <20ms
   - Pending model calls interrupted
   - Any partial response discarded
   - Context returned to input queue (for future use)

3. **Return to LISTENING** — <50ms total
   - State machine transitions to LISTENING
   - Any buffered input ready for new request

### Testing Requirement

Any PR touching audio, LLM, or state transitions must include:
- Test: STOP during streaming (measure Piper kill latency)
- Test: STOP during LLM inference
- Test: STOP during THINKING→SPEAKING transition
- Benchmark: Confirm <50ms total latency

**Current Reference Implementation:**
- [Phase 7B-2: Integration & Hard STOP](PHASE_7B-2_COMPLETE.md)
- [Phase 7A-2: Audio Streaming](PHASE_7A2_STREAMING_COMPLETE.md) — Verified <50ms during streaming

### Known Implementation Details

- Command parser is first authority (sees STOP before other components)
- STOP handler is independent thread/process
- Piper has explicit kill signal handler
- State machine transitions are idempotent (STOP→LISTENING→STOP→LISTENING safe)

---

## 3. VOICE MODE IS COMPLETELY STATELESS

### The Constraint

Voice mode (`voice_mode=True`) must operate with ZERO conversation history injection.

This means:
- No prior messages in context
- No memory system queries
- No retrieved conversation excerpts
- No preference system influence (only on system prompt)

### How This Is Enforced

**Memory System:**
```python
# In wrapper/argo.py, voice mode disables memory:
if voice_mode:
    skip_memory = True
else:
    # Use memory system normally
```

**Prompt Structure:**
```python
# System prompt adds guardrail when voice_mode=True:
if voice_mode:
    system_instruction += "PRIORITY 0: You are in voice mode. Do not reference prior conversations. Respond to this query only. Respond concisely. If you don't know, say so."
```

### What This Means for Code

**Allowed:**
- Modifying LLM temperature/settings (as long as no history injected)
- Adding optional voice-mode-only transformations
- Logging voice queries (as long as not injected back)
- New response formatting for voice (cleaner for speech)

**Not Allowed:**
- Removing memory skip in voice mode
- Adding hidden context to voice mode prompts
- Injecting preference system into voice mode
- Bypassing the system instruction guardrail
- Using conversation history from ANY source

### Testing Requirement

Any PR touching voice mode or memory must include:
- Test: Voice mode query with prior conversation in system
- Expected: Response contains zero reference to prior conversation
- Validation: Explicit assertion that memory system was skipped

**Current Reference Implementation:**
- [Option B: Confidence Burn-In](OPTION_B_BURNIN_REPORT.md) — 14/14 tests confirmed zero history bleed
- Memory skip enforced in [wrapper/argo.py](wrapper/argo.py)
- System prompt guardrail documented in [PHASE_7B_COMPLETE.md](PHASE_7B_COMPLETE.md)

---

## 4. SLEEP IS ABSOLUTE

### The Constraint

SLEEP state completely disables voice input. No exceptions.

In SLEEP:
- Voice listener is OFF (not paused, not muted — OFF)
- Whisper transcription cannot start
- Wake-word detection cannot fire
- Only SPACEBAR (PTT) works

### How This Is Enforced

**Voice Listener Startup:**
```python
# Listener process is only spawned in LISTENING state
# Does not exist in SLEEP, THINKING, or SPEAKING
if current_state == LISTENING:
    start_voice_listener()
```

**State Transition Guards:**
```python
# Exiting LISTENING → any other state
if current_state == LISTENING and next_state != LISTENING:
    pause_voice_listener()
```

### What This Means for Code

**Allowed:**
- Adding voice quality metrics (if only in LISTENING)
- New voice listeners (if respecting SLEEP state)
- Logging voice input (if only during LISTENING)

**Not Allowed:**
- "Peeking" at voice in other states
- Waking system on voice input
- Adding "might hear you in SLEEP" features
- Disabling SLEEP voice guard for any reason

### Testing Requirement

Any PR touching voice or state transitions must include:
- Test: Speak while in SLEEP → no response
- Test: User says "STOP" while in SLEEP → no state change
- Test: SPACEBAR PTT works in SLEEP → manual control works
- Validation: Listener process verified as not running in SLEEP

**Current Reference Implementation:**
- [Option B: Confidence Burn-In](OPTION_B_BURNIN_REPORT.md) — SLEEP validation (Tier 1, Test 4)

---

## 5. PROMPT HYGIENE IS ENFORCED

### The Constraint

System instruction structure must prevent context leakage even if bugs exist elsewhere.

The system instruction is structured as:

```
PRIORITY 0: [Safety guardrails specific to current mode]
PRIORITY 1: [Task description]
PRIORITY 2: [Output format]

[If memory/context is injected, it comes AFTER priority layers]
```

This means:
- If memory system has a bug and injects history anyway, PRIORITY 0 still dominates
- If a new feature accidentally adds context, PRIORITY layers still hold
- System instruction is the last line of defense

### How This Is Enforced

**Voice Mode Guardrail:**
```python
system_instruction = """PRIORITY 0: You are in voice mode. Do not reference prior conversations. Respond only to the current query. Be concise.
PRIORITY 1: Answer the following question...
"""
```

**Memory System Independence:**
```python
# Memory context added AFTER priority layers, not before
# Visible in logs
context = get_memory_context()
full_prompt = system_instruction + context + user_query
```

### What This Means for Code

**Allowed:**
- Reorganizing prompt structure (if priority layers maintained)
- Adding new priority layers (if they don't conflict)
- Improving memory retrieval (must still come AFTER priorities)

**Not Allowed:**
- Removing priority layers
- Moving memory context before priorities
- Removing voice mode guardrail
- Assuming any single component will prevent context bleed

### Testing Requirement

Any PR touching prompts or memory must include:
- Test: Prompt structure validated (priority layers exist)
- Test: Voice mode in context with prior conversation
- Expected: System instruction dominates, no history in response
- Validation: Full prompt logged for audit

**Current Reference Implementation:**
- [PHASE_7B_COMPLETE.md](PHASE_7B_COMPLETE.md) — Priority layer design
- [wrapper/argo.py](wrapper/argo.py) — build_behavior_instruction() implementation

---

## 6. AUDIO STREAMING IS NON-BLOCKING

### The Constraint

Audio playback must not block user input or control flow.

Streaming implementation:
- Piper synthesis runs in background thread
- Audio frames buffered and played incrementally
- User can press SPACEBAR or "STOP" at any time
- STOP response is <50ms even during playback

### Latency Target

- Time-to-first-audio: ~500-900ms (from query submission to audio start)
- This is IMPROVEMENT, not regression
- Baseline (Phase 7A-2 established): TTFA 485-830ms across 5 tests

### How This Is Enforced

**Streaming Architecture:**
```python
# core/output_sink.py
def _play_audio(self, text):
    process = subprocess.Popen(piper_args)  # Async subprocess
    self._stream_audio_data(process)  # Reads frames incrementally
    # Returns immediately, doesn't wait for synthesis

def _stream_audio_data(self, process):
    # Reads frames from Piper in background
    # Starts playback at 200ms buffer threshold
    # Returns to caller immediately
```

### What This Means for Code

**Allowed:**
- Tuning buffer thresholds (if profiled)
- Adding stream quality monitoring
- Optimizing frame reading (if latency maintained)
- New audio backends (if non-blocking)

**Not Allowed:**
- Returning to blocking Piper process wait
- Removing background threading
- Increasing TTFA beyond current baseline
- Making audio playback synchronous

### Testing Requirement

Any PR modifying audio playback must include:
- Test: Measure TTFA for 3 different query lengths
- Expected: TTFA < 1000ms consistently
- Test: STOP during playback → <50ms response
- Benchmark: Streaming still works for long responses

**Current Reference Implementation:**
- [Phase 7A-2: Audio Streaming](PHASE_7A2_STREAMING_COMPLETE.md)
- [core/output_sink.py](core/output_sink.py) — _stream_audio_data() implementation

---

## How to Respect the Foundation Lock

### Before You Code

1. **Read this document** ← You are here
2. **Identify which guarantee(s) your change touches:**
   - Modifying state machine? → Affects Guarantee 1
   - Touching Piper/audio? → Affects Guarantee 2 & 6
   - Voice mode or memory? → Affects Guarantee 3
   - State transitions? → Affects Guarantee 4
   - Prompts? → Affects Guarantee 5

3. **Read the relevant reference implementation:**
   - Find the document linked above for your guarantee
   - Understand how it currently works
   - Plan your change to enhance, not break

### As You Code

1. **Write tests for the guarantee**
   - From the Testing Requirement section above
   - Include measurement/validation
   - Make failure obvious

2. **Don't silence errors**
   - If STOP latency increases, let the test fail
   - If memory creeps into voice mode, let tests catch it
   - If state transitions break, let them be visible

3. **Document why**
   - In commit message: "Why this change respects Guarantee X"
   - In PR description: "Testing shows Guarantee X still holds"
   - In code comments: "This maintains Guarantee X because..."

### Before You Merge

1. **Verify all tests pass**
   - Existing tests (proof you didn't break anything)
   - New tests (proof your change works)

2. **Benchmark the guarantee**
   - STOP latency still <50ms? ✓
   - Voice still stateless? ✓
   - SLEEP still disabled voice? ✓
   - Streaming still responsive? ✓

3. **Get review from someone who cares**
   - Share PR with focus on: "Here's which guarantee(s) I touched, here's how I maintained them"
   - Provide measurements/logs as proof

---

## What Happens If a Guarantee Is Broken

If a PR or commit breaks any guarantee:

1. **That release does NOT ship**
2. **The commit is reverted** (no exceptions)
3. **Root cause is documented** (why did the test not catch this?)
4. **The test is strengthened** (add assertion to prevent recurrence)
5. **Lessons learned are shared** (other devs learn from the failure)

This is not harsh. This is respectful to users who depend on these guarantees.

---

## FAQ: Foundation Lock

**Q: Can I make STOP faster than 50ms?**  
A: Yes! That's an enhancement, not a violation. Measure it and document.

**Q: Can I disable voice mode statelessness for a better answer?**  
A: No. The better answer is not worth compromising user privacy. Find another way.

**Q: Can I add a new state to the state machine?**  
A: Not silently. That's a major architecture change. Propose it, document it, get consensus.

**Q: What if I find the Foundation Lock is wrong?**  
A: Document why, propose a better constraint, get buy-in from stakeholders. Then change it explicitly in this file (with date and rationale).

**Q: Can I violate a guarantee if I add a test?**  
A: No. Tests verify guarantees; they don't replace them. The guarantee is the requirement; tests are proof.

**Q: What about performance optimization that requires breaking a guarantee?**  
A: Find a different optimization. These guarantees are non-negotiable. Period.

**Q: Is the foundation locked forever?**  
A: No. It's locked for v1.0.0-voice-core. Future releases can propose changes. But they must be explicit, documented, and accepted by the community.

---

## Revision History

| Date | Change | Reason |
|------|--------|--------|
| 2026-01-18 | Initial Foundation Lock created | v1.0.0-voice-core release, 6 guarantees established |

---

*This is the foundation. Everything else is built on top of it.*

*Do not be clever. Be reliable.*
