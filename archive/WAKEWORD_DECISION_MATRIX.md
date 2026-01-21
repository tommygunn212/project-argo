# WAKEWORD_DECISION_MATRIX.md

**Purpose**: Complete reference table for all wake-word trigger scenarios and outcomes  
**Audience**: Implementers, testers, designers  
**Format**: Lookup table (if X then Y)  

---

## Master Trigger-Outcome Matrix

### Dimension 1: State Machine State

```
State | Wake-Word Active? | PTT Processable? | STOP Effective?
------|------------------|-----------------|----------------
SLEEP | NO               | NO              | YES (no-op)
LISTENING | YES          | YES             | YES (no-op)
THINKING | NO             | NO              | YES (cancel LLM)
SPEAKING | NO             | NO              | YES (kill Piper)
```

### Dimension 2: Input Combinations (What Happens?)

#### CASE 1: LISTENING State + Wake-Word + No PTT + No STOP

| Trigger | Condition | Action | Result |
|---------|-----------|--------|--------|
| "ARGO" spoken | Confidence >= 0.85 | Detector fires recognition | Transition LISTENING → THINKING |
| "ARGO" spoken | Confidence < 0.85 | Detector ignores | Remain LISTENING (no event) |
| Ambient noise | Similarity to "ARGO" < 70% | Detector rejects | Remain LISTENING |
| False positive | Recognition fires anyway | LLM receives empty input | Ambiguity response ("clarify") |

**Expected Behavior**: Clean transition to thinking, LLM processes query, or silent ignore.

---

#### CASE 2: LISTENING State + Wake-Word + PTT Active + No STOP

| Trigger | Condition | Action | Result |
|---------|-----------|--------|--------|
| "ARGO" spoken | PTT SPACEBAR held | Wake-word paused | PTT input captured by Whisper, wake-word ignored |
| Detector fires | PTT already processing | Event queued | Wake-word event discarded after PTT completes |
| User releases SPACEBAR | Wake-word was buffered | Detector resumes | Wake-word reactivated if still in LISTENING |

**Expected Behavior**: PTT always wins. Wake-word paused while PTT active. No conflict.

---

#### CASE 3: LISTENING State + Wake-Word + STOP Command

| Trigger | Condition | Action | Result |
|---------|-----------|--------|--------|
| "ARGO" + immediate "STOP" | Both in same utterance | STOP parsed first | Remain LISTENING, no transition |
| "ARGO" recognized | User says "STOP" | STOP cancels recognition | Wake-word event discarded, buffer cleared |
| False positive occurring | User says "STOP" | STOP interrupts | Recognition cancelled, clean exit |

**Expected Behavior**: STOP wins, wake-word cancelled, return to LISTENING.

---

#### CASE 4: THINKING State + Any Wake-Word Attempt

| Trigger | Condition | Action | Result |
|---------|-----------|--------|--------|
| User speaks "ARGO" | System thinking | Wake-word ignored | LLM continues processing, no double-trigger |
| Detector fires | While LLM active | Event discarded | No queuing, no interrupt, no transition |
| Multiple detections | During single response | All ignored | State machine remains THINKING |

**Expected Behavior**: Wake-word completely disabled during THINKING. No conflicts.

---

#### CASE 5: SPEAKING State + Any Wake-Word Attempt

| Trigger | Condition | Action | Result |
|---------|-----------|--------|--------|
| User speaks "ARGO" | Audio streaming | Wake-word ignored | Audio continues, no transition |
| Detector fires | During Piper playback | Event discarded | No queueing |
| "STOP" spoken | Wake-word or not | STOP processes first | Piper killed, transition to LISTENING |

**Expected Behavior**: Wake-word disabled while audio plays. STOP still works (state machine authority).

---

#### CASE 6: SLEEP State + Wake-Word + Any Condition

| Trigger | Condition | Action | Result |
|---------|-----------|--------|--------|
| "ARGO" spoken | System asleep | Detector disabled | No recognition (listener off) |
| Loud noise matches | Sounds like "ARGO" | Detector not running | No false wake (listener off) |
| PTT during sleep | User holds SPACEBAR | PTT not processed | System remains SLEEP |
| "ARGO" + "wake up" | Explicit wake command | PTT processes "wake up" | Transition to LISTENING (on PTT, not wake-word) |

**Expected Behavior**: Absolutely silent. SLEEP is absolute authority. Wake-word disabled completely.

---

## False-Positive Behavior Matrix

| FP Scenario | Detection | Outcome | User Experience |
|-------------|-----------|---------|-----------------|
| "Large Oh" (sounds like "ARGO") | Detector fires confidence 0.87 | System transitions LISTENING → THINKING, LLM receives empty input | "Please clarify" response (no indication of FP) |
| Dog bark similar | Confidence 0.82 | Detector rejects (below threshold 0.85) | Silent, remain LISTENING |
| Echo of own response | Confidence 0.91 | System transitions (treated as true positive) | May trigger second response (acceptable) |
| Heavy accent variant | Confidence varies | Depends on training data quality | May or may not trigger (tolerance acceptable) |

**Rule**: False positives are silent failures. The ambiguity handler catches them and prompts for clarification.

---

## PTT Override Precedence Matrix

| User Input | Wake-Word Status | PTT Status | Winner | Behavior |
|------------|-----------------|-----------|--------|----------|
| "ARGO" | Ready | Ready | PTT | Wake-word paused, PTT captures audio |
| "ARGO" | Ready | Releasing | Wake-word | Processed as wake-word |
| "ARG" + SPACEBAR held | Ready | Active | PTT | PTT input, wake-word ignored |
| "stop" | Ready | Not active | State machine | STOP processes (always first) |
| Silent | Neither | Neither | Neither | Idle, waiting |

**Priority Order**:
1. STOP (command parser, universal)
2. PTT (explicit user input)
3. Wake-word (automated detection)

---

## STOP Dominance Matrix

| Action | STOP Triggered? | Current State | Result |
|--------|-----------------|---------------|--------|
| Wake-word recognition in progress | Yes | LISTENING | Cancel recognition, buffer cleared, remain LISTENING |
| Wake-word just fired | Yes | LISTENING → THINKING (transition) | Block transition, cancel event, remain LISTENING |
| PTT input active | Yes | LISTENING | Stop PTT processing, clear buffer, remain LISTENING |
| LLM thinking | Yes | THINKING | Cancel LLM task, transition THINKING → LISTENING |
| Piper streaming | Yes | SPEAKING | Kill process, transition SPEAKING → LISTENING |
| System asleep | Yes | SLEEP | No-op (already idle) |

**Guarantee**: STOP latency <50ms regardless of wake-word state.

---

## State Transition Guard Matrix

| Attempted Transition | Guard | Allow? | Reason |
|----------------------|-------|--------|--------|
| LISTENING → THINKING (wake-word) | None | YES | Wake-word can trigger transition |
| LISTENING → THINKING (PTT) | None | YES | PTT can trigger transition |
| LISTENING → THINKING (STOP) | Stop event blocks | NO | STOP keeps in LISTENING |
| THINKING → LISTENING (wake-word) | State guard | NO | Already thinking, ignore wake-word |
| THINKING → SPEAKING (wake-word) | State guard | NO | Wake-word disabled during THINKING |
| SPEAKING → LISTENING (wake-word) | State guard | NO | Wake-word disabled during SPEAKING |
| SLEEP → LISTENING (wake-word) | Sleep guard | NO | Wake-word disabled in SLEEP |
| SLEEP → LISTENING (PTT + "wake up") | Explicit command | YES | PTT can request wakeup |
| ANY → LISTENING (STOP) | STOP handler | YES | STOP always transitions to LISTENING |
| ANY → SLEEP ("go to sleep") | SLEEP command | YES | Sleep command always works |

**Philosophy**: State machine is gate. Wake-word requests transition; state machine decides.

---

## Edge Case Resolution Matrix

| Edge Case | Scenario | Design | Outcome |
|-----------|----------|--------|---------|
| Double trigger (wake-word + PTT simultaneously) | User says "ARGO" while holding SPACEBAR | PTT priority | PTT wins, wake-word ignored |
| Rapid false positives | Detector fires 3x in 2 seconds | State gate | First transition to THINKING, rest ignored |
| STOP mid-wake-word | User says "ARGO stop" as single burst | Command parser order | STOP parsed first, no transition |
| Wake-word while asleep | User tests sleeping system | Listener off | Silent, no wake (absolute SLEEP) |
| False positive → STOP | Ambient triggers system, user interrupts | Normal flow | "Please clarify" response, then STOP clears it |
| Wake-word → PTT immediately after | User says "ARGO", immediately starts speaking | State transition | Transition to THINKING completes first, then PTT queued |
| CPU spike on wake-word | Detector activating | Resource guard | Must be <5% idle (non-negotiable) |
| Confidence threshold tuning | Too many false positives | Pre-implementation | Threshold increased (0.85 → 0.90) before ship |

---

## Failure Mode Resolution Matrix

| Failure Mode | Detection | Recovery | Prevention |
|--------------|-----------|----------|-----------|
| Detector process crashes | Supervisor detects exit code | Restart detector, resume operation | Use robust detector, monitor uptime |
| High false-positive rate | >5% anomaly monitoring | Increase threshold (requires redeployment) | Test on realistic audio data |
| PTT latency degraded | Streaming profiling shows >5% CPU | Reduce detector load (lighter model) | Pre-integration testing |
| Wake-word blocks STOP | STOP latency >50ms | Investigate state machine | Ensure STOP not blocked by detector |
| Memory leak in detector | Memory usage grows | Restart detector periodically | Use memory-safe detector library |
| SLEEP state not respected | Wake-word fires when asleep | Verify listener off guard | Code review before ship |

---

## Test Matrix (For Validation Phase)

### Test Case: Wake-Word Basic

| Test | Precondition | Action | Expected | Pass? |
|------|-------------|--------|----------|-------|
| T1.1 | LISTENING state | User says "ARGO" | Transition to THINKING | TBD |
| T1.2 | LISTENING state | Ambient noise | Remain LISTENING | TBD |
| T1.3 | LISTENING state | User says "ARGO" quietly | Remain LISTENING (confidence too low) | TBD |

### Test Case: PTT Override

| Test | Precondition | Action | Expected | Pass? |
|------|-------------|--------|----------|-------|
| T2.1 | LISTENING + SPACEBAR held | User says "ARGO" | PTT captures input, wake-word ignored | TBD |
| T2.2 | LISTENING state | Release SPACEBAR, then "ARGO" | Wake-word processes after PTT done | TBD |
| T2.3 | LISTENING + PTT active | Wake-word event queued | Wake-word discarded when PTT ends | TBD |

### Test Case: STOP Dominance

| Test | Precondition | Action | Expected | Pass? |
|------|-------------|--------|----------|-------|
| T3.1 | Wake-word recognition | User says "STOP" | Recognition cancelled, LISTENING | TBD |
| T3.2 | THINKING state | User says "STOP" | LLM task cancelled, LISTENING | TBD |
| T3.3 | SPEAKING state | User says "STOP" | Piper killed, LISTENING | TBD |

### Test Case: SLEEP Authority

| Test | Precondition | Action | Expected | Pass? |
|------|-------------|--------|----------|-------|
| T4.1 | SLEEP state | User says "ARGO" | Silent (wake-word disabled) | TBD |
| T4.2 | SLEEP state | User holds SPACEBAR | Silent (PTT disabled while asleep) | TBD |
| T4.3 | LISTENING → SLEEP | User says "go to sleep" then "ARGO" | SLEEP confirmed, no wake | TBD |

---

## Sign-Off Matrix

### Phase 7A-3a Acceptance Criteria

| Criterion | Yes/No | Evidence | Reviewer |
|-----------|--------|----------|----------|
| Wake-word design fully specified | [ ] | PHASE_7A3_WAKEWORD_DESIGN.md | Bob |
| All edge cases have behaviors | [ ] | This matrix | Bob |
| STOP dominance unquestionable | [ ] | STOP matrix above | Bob |
| State machine intact (no bypasses) | [ ] | State transition guards | Bob |
| False positives are silent | [ ] | FP behavior matrix | Bob |
| Resource model measured (<5% CPU idle) | [ ] | Detector profiling | Bob |
| PTT always wins | [ ] | PTT precedence matrix | Bob |
| SLEEP is absolute | [ ] | SLEEP matrix | Bob |
| No implementation has begun | [ ] | Code review (none exists) | Bob |

---

*Document Complete*: 2026-01-18  
*Format*: Decision reference matrix  
*Audience*: Developers, testers, architects  
*Next*: GO/NO-GO checklist
