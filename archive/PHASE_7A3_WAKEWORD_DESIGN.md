# Phase 7A-3a: Wake-Word Detection - Architecture Design

**Phase Status**: DESIGN ONLY (No Implementation)  
**Target**: Boring, predictable wake-word behavior coexisting cleanly with PTT  
**Date**: 2026-01-18  

---

## 1. WAKE-WORD ACTIVATION MODEL

### Definition: When Is Wake-Word Listening Active?

**Active (Listening)**:
- State machine is in `LISTENING` state
- System has completed a response or is idle
- SLEEP state has NOT been commanded
- User has not disabled wake-word explicitly

**Inactive (Not Listening)**:
- State machine is in `SLEEP` state (system explicitly asleep)
- State machine is in `THINKING` state (LLM is responding)
- State machine is in `SPEAKING` state (audio is playing)
- System is in `STARTUP` or `SHUTDOWN` states
- PTT input is active (SPACEBAR held, PTT takes precedence)

### Sleep State Interaction (Critical)

**Rule**: Wake-word is completely disabled in SLEEP state.

```
LISTENING state
  ├─ Wake-word listener: ACTIVE (listening for "ARGO")
  └─ Can transition to: THINKING (on wake-word) OR SLEEPING (on "go to sleep")

SLEEPING state
  ├─ Wake-word listener: DISABLED (not running)
  ├─ Microphone: CLOSED (no input processing)
  └─ Can only transition to: LISTENING (on explicit "wake up" command)

THINKING state
  ├─ Wake-word listener: DISABLED (would conflict with response synthesis)
  └─ Can transition to: SPEAKING (response ready)

SPEAKING state
  ├─ Wake-word listener: DISABLED (audio playing, avoid conflicts)
  └─ Can transition to: LISTENING (audio finished)
```

**Rationale**: SLEEP is absolute authority. Wake-word cannot override it. This preserves user agency and prevents unexpected activations.

### Wake-Word Does NOT Wake Sleeping System

**Requirement**: A sleeping (SLEEP state) ARGO cannot be awakened by the wake-word "ARGO" alone.

**Method to Exit SLEEP**:
1. PTT: User holds SPACEBAR (always works)
2. Explicit command: "Wake up" from PTT input (future enhancement)
3. System reboot (new session)

**Why**: Sleep is user-initiated and must remain user-controlled. Accidental utterances should not wake the system.

---

## 2. COEXISTENCE WITH PUSH-TO-TALK (PTT)

### PTT Always Wins (Non-Negotiable)

**Rule**: PTT input takes absolute precedence over wake-word.

### State of Play During PTT

```
PTT Active (SPACEBAR held):
  ├─ User is speaking (Whisper capturing)
  ├─ Wake-word listener: PAUSED (not listening, would create conflicts)
  ├─ Audio input: Captured by Whisper (PTT channel)
  └─ State: Remains LISTENING (no transition yet)

PTT Release:
  ├─ Whisper processes captured audio
  ├─ Wake-word listener: RESUMED (re-enabled)
  ├─ If recognized: Transition to THINKING (response generation)
  └─ If not recognized: Remain in LISTENING (await next input)
```

### Priority Matrix

| Scenario | Wake-Word Active? | PTT Active? | Behavior | Winner |
|----------|------------------|------------|----------|--------|
| Both triggered | Yes | Yes | PTT takes input, wake-word ignored | PTT |
| PTT active, wake-word hears "ARGO" | Yes | Yes | Wake-word ignored | PTT |
| Only wake-word | Yes | No | Process as voice input | Wake-word |
| Only PTT | Yes | Yes | Process as PTT input | PTT |
| Neither | No | No | Idle, listening | Neither (wait) |

**Implementation Detail**: While PTT is active, wake-word detection is paused (not consuming CPU). When PTT is released, wake-word resumes.

---

## 3. STOP DOMINANCE (Critical)

### STOP Override (Absolute)

**Rule**: STOP command must interrupt wake-word listening immediately, with no exceptions.

### STOP Interrupt Scenarios

```
Scenario 1: STOP during wake-word detection
  ├─ User says "ARGO" (wake-word detection in progress)
  ├─ User says "stop" before recognition completes
  ├─ Behavior: Cancel wake-word recognition, transition to LISTENING
  └─ Latency: <50ms (state machine authority)

Scenario 2: STOP during wake-word audio buffer
  ├─ Wake-word has buffered audio
  ├─ User says "stop"
  ├─ Behavior: Clear audio buffer, remain in LISTENING
  └─ Latency: <50ms (buffer flush)

Scenario 3: STOP during transition from wake-word to THINKING
  ├─ Wake-word recognized, about to transition
  ├─ User says "stop" in same command burst
  ├─ Behavior: Don't transition, stay LISTENING
  └─ Latency: <50ms (transition guard)

Scenario 4: STOP while SPEAKING (already active response)
  ├─ Piper audio streaming
  ├─ User says "stop"
  ├─ Behavior: Kill Piper process, transition SPEAKING -> LISTENING
  └─ Latency: <50ms (process termination, existing behavior)
```

### Design: Wake-Word Never Suppresses STOP

**Implementation**: STOP is handled at command parser level (existing), wake-word is subprocess. If STOP is recognized during wake-word listening, stop handler immediately:
1. Cancels any pending wake-word recognition task
2. Clears audio buffer
3. Transitions state machine to LISTENING
4. Resumes normal input handling

**Guarantee**: STOP path is independent of wake-word detection. The command parser sees STOP first.

---

## 4. RESOURCE MODEL

### Detection Method: Lightweight Keyword Spotting (LKS)

**Chosen Approach**: Lightweight keyword spotting detector (not full Whisper)

**Rationale**:
- Whisper is too heavy (~1GB model, high CPU when idle)
- Keyword spotting is designed for always-on detection
- Can run continuously on CPU without degrading TTS/streaming
- Typical models: ~50MB, optimizable for mobile
- Latency: ~100-200ms (acceptable for wake-word)

**Alternative Rejected**: Continuous Whisper
- Would consume 30-50% CPU while idle
- Would impact audio streaming quality
- Too resource-intensive

### CPU vs GPU Path

**Idle CPU Usage Target**: <5% when listening

**Paths**:
- **CPU Path** (Default): Lightweight detector runs on CPU, minimal overhead
- **GPU Path** (Future): Offload to GPU if available (out of scope)

**Measurement Point**: Profile idle CPU consumption before implementation. If >5%, choose different detector or implement GPU path.

### Wake-Word Uses Lightweight Detector

**System Used**:
- Pre-trained keyword spotter (e.g., TensorFlow Lite or similar)
- Models "ARGO" as single keyword
- Processes 50ms audio chunks
- Confidence threshold: 0.85 (adjustable)

**Not Used**:
- ❌ Full Whisper (too heavy)
- ❌ Continuous streaming to cloud (no external deps)
- ❌ Browser-based detection (this is CLI)

### Resource Budgets

| Component | Idle CPU | Active | Memory | Notes |
|-----------|----------|--------|--------|-------|
| Wake-word detector | <5% | 10-15% | ~50MB | Lightweight model only |
| Whisper (PTT) | 0% | 30-40% | ~1GB | Existing, only on PTT |
| Piper (TTS) | 0% | 20-30% | ~300MB | Existing, only when speaking |
| State machine | <1% | <1% | <5MB | No change |
| Overall idle | <5% | N/A | ~50MB | Detector dominates idle |

**Non-Negotiable**: Streaming latency must not degrade. Wake-word must run independently.

---

## 5. FALSE-POSITIVE STRATEGY

### Acceptable False-Positive Rate

**Target**: <5% false-positive rate
- Meaning: Out of 100 hours of idle listening, <5 false activations

**Measurement**: Before implementation, define how to measure (sensitivity analysis).

### What Happens on False Wake

**Behavior**: Silent failure

```
False Positive Scenario:
  ├─ User says "large Oh" (sounds like "ARGO")
  ├─ Detector fires (confidence >= threshold)
  ├─ System transitions LISTENING -> THINKING
  ├─ No spoken confirmation ("Listening" or "Yes?")
  ├─ LLM receives empty input (user was not addressing system)
  ├─ LLM responds with "Input is ambiguous. Please clarify."
  ├─ State transitions THINKING -> SPEAKING (normal flow)
  └─ Audio plays: "Please clarify..."

User Experience:
  ├─ Unexpected response from ambient speech
  ├─ User says "never mind" or "stop"
  ├─ System returns to LISTENING
  └─ Continues normal operation
```

**Rationale**: No explicit confirmation message needed. Ambiguity handler catches it.

**Alternative Rejected**: Spoken confirmation
- Would add latency (wake-word + confirmation wait)
- Would be annoying on true positives ("Yes?" every time)
- Breaks boring, quiet behavior goal

### Design: No Confirmation Required

Wake-word recognition directly triggers transition to THINKING. No intermediate confirmation state.

---

## 6. STATE MACHINE INTERACTION

### State Diagram with Wake-Word

```
    ┌─────────────────────────────────────┐
    │          SLEEP STATE                │
    │   (Wake-word listener DISABLED)     │
    │   (Mic CLOSED)                      │
    └────────────────────┬────────────────┘
                         │ PTT + "wake up"
                         │ (explicit wakeup)
                         ▼
    ┌─────────────────────────────────────┐
    │        LISTENING STATE              │
    │   (Wake-word listener ACTIVE)       │
    │   (Idle, awaiting input)            │
    └───────────┬──────────┬──────────────┘
                │          │
    PTT         │          │ Wake-word "ARGO"
    (SPACEBAR)  │          │ (spoken command)
                │          │
                ▼          ▼
    ┌──────────────────────────────────────┐
    │       THINKING STATE                 │
    │   (Wake-word listener DISABLED)      │
    │   (LLM generating response)          │
    └────────────────┬─────────────────────┘
                     │ Response ready
                     ▼
    ┌──────────────────────────────────────┐
    │       SPEAKING STATE                 │
    │   (Wake-word listener DISABLED)      │
    │   (Audio streaming via Piper)        │
    └────────────────┬─────────────────────┘
                     │ STOP or audio ends
                     ▼
    ┌──────────────────────────────────────┐
    │       LISTENING STATE (again)        │
    │   (Wake-word listener ACTIVE)        │
    └──────────────────────────────────────┘

At ANY state: "go to sleep" → SLEEP
At ANY state: "stop" → LISTENING (interrupt current operation)
```

### Wake-Word Triggers Request, Not Override

**Critical Rule**: Wake-word does NOT force state transition. It requests transition.

```
Wake-word recognition flow:

1. Detector fires: "ARGO" recognized
2. Signal: Send recognition event to state machine
3. State machine processes: Check current state
   ├─ If LISTENING: Grant transition to THINKING
   ├─ If THINKING: Ignore (already processing)
   ├─ If SPEAKING: Ignore (audio playing)
   └─ If SLEEP: Ignore (asleep, wake-word disabled anyway)
4. Result: Transition to THINKING (if state allows) or no-op
```

**State Machine Authority**: State machine decides whether to honor wake-word request based on current state.

### Prevention of State Bypasses

**Guarantee**: Wake-word cannot bypass state machine.

```
Guards against:
  ├─ Wake-word forcing LISTENING->SPEAKING (no, must go LISTENING->THINKING->SPEAKING)
  ├─ Wake-word forcing SLEEP->THINKING (no, SLEEP is absolute)
  ├─ Wake-word during THINKING (no, ignored, system already responding)
  └─ Wake-word during SPEAKING (no, ignored, audio playing)
```

---

## 7. PRIORITY RULES (Comprehensive)

### Priority Order (Highest to Lowest)

```
1. STOP command (system interrupt, universal)
2. SLEEP command (state override, absolute)
3. PTT input (user explicit action, SPACEBAR)
4. Wake-word input (automated detection)
5. Idle (awaiting input)
```

**Implication**: Wake-word is lowest priority (only triggers when nothing else is happening).

### Interaction Matrix

| Current State | PTT Active? | Wake-Word Fires? | STOP Command? | Behavior |
|---------------|------------|-----------------|---------------|----------|
| LISTENING | No | Yes | No | Wake-word triggers THINKING |
| LISTENING | No | No | No | Remain LISTENING |
| LISTENING | Yes | Yes | No | PTT wins, process PTT input |
| LISTENING | Yes | No | Yes | STOP (no-op, already idle) |
| LISTENING | No | No | Yes | STOP (no-op, already idle) |
| THINKING | No | Yes | No | Wake-word ignored |
| THINKING | Yes | No | No | PTT ignored (already thinking) |
| THINKING | No | No | Yes | STOP cancels LLM (transition to LISTENING) |
| SPEAKING | No | Yes | No | Wake-word ignored |
| SPEAKING | Yes | No | No | PTT buffered (processed next) |
| SPEAKING | No | No | Yes | STOP kills Piper (transition to LISTENING) |
| SLEEP | No | Yes | No | Wake-word ignored |
| SLEEP | Yes | No | No | PTT not processed (asleep) |
| SLEEP | No | No | Yes | STOP (no-op, already asleep) |

---

## 8. EDGE CASES AND BEHAVIORS

### Edge Case 1: Wake-Word While PTT Starting

**Scenario**: User begins holding SPACEBAR while saying "ARGO"

```
Timeline:
  T0: User utters "ARGO"
  T10ms: Wake-word detector recognizes audio
  T20ms: User holds SPACEBAR (PTT activates)
  
Behavior:
  ├─ Wake-word event queued
  ├─ PTT input takes precedence (PTT is explicit)
  ├─ Wake-word event discarded
  ├─ Whisper processes SPACEBAR audio as PTT
  └─ Result: PTT wins, wake-word ignored
```

**Rule**: PTT always wins if active.

### Edge Case 2: Multiple Wake-Words in Burst

**Scenario**: Background noise triggers "ARGO" multiple times rapidly

```
Timeline:
  T0: First recognition → transition to THINKING
  T50ms: Second "ARGO" detected
  
Behavior:
  ├─ Already in THINKING state
  ├─ Second wake-word ignored (guard prevents multi-trigger)
  ├─ Only one LLM query initiated
  └─ Result: Single response (boring, predictable)
```

**Rule**: State machine is gate. Multiple wake-words in same response cycle ignored.

### Edge Case 3: STOP During Wake-Word Detection

**Scenario**: User recognizes false positive, says STOP

```
Timeline:
  T0: Background noise triggers detector
  T100ms: False confidence building
  T120ms: User says "STOP"
  
Behavior:
  ├─ STOP command processed first (parser priority)
  ├─ Wake-word recognition cancelled
  ├─ Audio buffer cleared
  ├─ Remain in LISTENING
  └─ Result: Clean interrupt, return to idle
```

**Rule**: STOP cancels pending recognition immediately.

### Edge Case 4: Wake-Word While Sleeping

**Scenario**: System asleep, user says "ARGO" (testing)

```
Timeline:
  T0: System in SLEEP state
  T100ms: User says "ARGO"
  
Behavior:
  ├─ Wake-word detector is disabled (guard)
  ├─ No recognition event generated
  ├─ System remains in SLEEP
  ├─ Microphone remains closed
  └─ Result: Silent (no response, as designed)
```

**Rule**: Wake-word disabled in SLEEP means literally no listening occurs.

---

## 9. FAILURE MODES AND RECOVERY

### Failure 1: Detector Crashes

**Scenario**: Wake-word detector process dies unexpectedly

**Detection**: Supervisor detects process gone.

**Recovery**:
1. Log error
2. Restart detector
3. Resume normal operation
4. Inform user (via logs, not spoken)

**User Experience**: Brief pause (seconds), system recovers silently.

### Failure 2: High False-Positive Rate (Tuning Issue)

**Scenario**: >5% false-positives after deployment

**Detection**: Monitoring detects anomaly.

**Recovery**:
1. Increase confidence threshold (0.85 → 0.90)
2. Requires redeployment (cannot tune live)
3. Trade-off: Fewer false positives, fewer true positives

**Rule**: Tuning happens before implementation, not after.

### Failure 3: Wake-Word Blocks PTT

**Scenario**: Wake-word listener consuming CPU, PTT latency degraded

**Detection**: Profiling shows >10% idle CPU on wake-word.

**Recovery**:
1. Not acceptable—must fix before ship
2. Choose lighter detector model or GPU offload
3. Redesign if necessary (may abandon wake-word)

**Rule**: Streaming latency is non-negotiable. If wake-word breaks it, wake-word fails.

---

## 10. VALIDATION AND ACCEPTANCE

### Pre-Implementation Checklist

Before writing ANY code:

- [ ] Lightweight detector model selected and profiled
- [ ] CPU consumption measured at <5% idle
- [ ] Confidence threshold determined (0.85 proposed)
- [ ] False-positive rate measured on training set
- [ ] Streaming latency verified unchanged with detector running
- [ ] State machine modification plan reviewed (should be minimal)
- [ ] PTT interaction tested (on paper)
- [ ] STOP precedence confirmed
- [ ] SLEEP behavior locked

### Definition of Done

Phase 7A-3a is complete when:

✅ Architecture is fully specified (no hand-waving)  
✅ All edge cases have defined behaviors  
✅ STOP dominance is unquestionable  
✅ State machine integration causes no surprises  
✅ False positives are silent failures  
✅ PTT always wins  
✅ SLEEP is absolute  
✅ Resource model is measured (not estimated)  

### Go/No-Go Criteria (See separate document)

---

## 11. WHAT IS NOT IN THIS PHASE

❌ Allen voice (Phase 7D)  
❌ Voice personality (Phase 7D)  
❌ Voice switching (Phase 7D)  
❌ Memory integration (separate phase)  
❌ Tool calling (separate phase)  
❌ Autonomy (separate phase)  
❌ Music playback (separate phase)  
❌ Confirmation messages (design decision: no)  

---

## Summary

Wake-word detection is designed to be boring and predictable:

- **Active only in LISTENING state** (disabled elsewhere)
- **Paused during PTT** (PTT always wins)
- **Cancelled by STOP** (<50ms, absolute)
- **Disabled in SLEEP** (user agency preserved)
- **Uses lightweight detector** (<5% idle CPU)
- **False positives are silent** (ambiguity handler catches them)
- **State machine is authoritative** (wake-word requests, doesn't override)

This design is safe to implement. All behaviors are predictable and boring.

---

*Design Complete*: 2026-01-18 Phase 7A-3a  
*Status*: Ready for acceptance review
