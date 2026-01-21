# GO/NO-GO Checklist for Phase 7A-3 Implementation

**Purpose**: Explicit conditions that must be met before wake-word implementation begins  
**Status**: Design phase (no code written yet)  
**Date**: 2026-01-18  

---

## Part 1: Design Acceptance Criteria

### ✅ Criterion 1: Architecture Fully Specified (No Vague Language)

**Requirement**: Every behavior on paper must be precise. No hand-waving.

**Checkpoints**:

- [ ] **1.1**: Wake-word listener state defined for every state machine state
  - Evidence: PHASE_7A3_WAKEWORD_DESIGN.md sections 1-6
  - Acceptable: "Wake-word listener is DISABLED in SLEEP state" (precise)
  - Unacceptable: "Wake-word is mostly disabled in SLEEP" (vague)

- [ ] **1.2**: PTT override behavior completely specified
  - Evidence: WAKEWORD_DECISION_MATRIX.md PTT section
  - Acceptable: "PTT pauses wake-word listener while SPACEBAR held"
  - Unacceptable: "PTT probably takes precedence" (uncertain)

- [ ] **1.3**: STOP interrupt path fully mapped
  - Evidence: WAKEWORD_DECISION_MATRIX.md STOP section
  - Acceptable: "STOP command handler cancels wake-word recognition task in <50ms"
  - Unacceptable: "STOP might interrupt wake-word" (uncertain)

- [ ] **1.4**: State transition guards completely defined
  - Evidence: State transition guard matrix
  - Acceptable: "Wake-word cannot force SLEEP→THINKING transition"
  - Unacceptable: "Wake-word tries to transition but may be blocked" (uncertain)

**Decision**: 
- [ ] PASS - All behaviors precisely specified
- [ ] FAIL - Vague language found, requires revision

---

### ✅ Criterion 2: STOP Dominance Unquestionable

**Requirement**: STOP must interrupt wake-word with zero ambiguity.

**Checkpoints**:

- [ ] **2.1**: STOP can cancel wake-word recognition mid-process
  - Evidence: STOP matrix, edge case 3
  - Test case: User says "ARGO" then "STOP" in rapid sequence
  - Expected: STOP processes first, wake-word cancelled
  - Latency: <50ms (state machine already handles this)

- [ ] **2.2**: STOP can clear wake-word audio buffer
  - Evidence: Design section 3, scenario 2
  - Mechanism: If audio buffered for recognition, STOP clears buffer
  - Result: Clean return to LISTENING

- [ ] **2.3**: STOP cannot be suppressed by wake-word
  - Evidence: Command parser always sees STOP first (architecture)
  - Architectural guarantee: STOP is parsed before wake-word detection runs
  - Design verification: STOP handler is independent of wake-word detector

- [ ] **2.4**: STOP latency is <50ms even during wake-word
  - Evidence: Existing STOP latency is <50ms (verified in Phase 7A-2)
  - Wake-word does not increase this latency
  - Assumption: Wake-word detector runs in separate thread/process

**Decision**:
- [ ] PASS - STOP dominance is architectural fact
- [ ] FAIL - Any ambiguity about STOP, return to design

---

### ✅ Criterion 3: State Machine Not Bypassed

**Requirement**: Wake-word must request transition, not override it.

**Checkpoints**:

- [ ] **3.1**: Wake-word cannot force LISTENING→SPEAKING (must go through THINKING)
  - Evidence: State transition guard matrix
  - Design: Wake-word only fires while LISTENING, can only trigger THINKING transition
  - Guard: SPEAKING state unreachable directly from wake-word

- [ ] **3.2**: Wake-word cannot bypass SLEEPING→LISTENING gate
  - Evidence: SLEEP matrix, design section 1
  - Guarantee: Wake-word listener is off in SLEEP state
  - Proof: Listener process not started until LISTENING state

- [ ] **3.3**: Wake-word cannot trigger during THINKING or SPEAKING
  - Evidence: State guards disable wake-word in those states
  - Implementation: Listener paused or ignored if triggered
  - Design: Only LISTENING state has active listener

- [ ] **3.4**: Multiple wake-words in same cycle prevented
  - Evidence: State machine gate prevents double-trigger
  - Design: Transition to THINKING makes state THINKING (listener disabled)
  - Result: Second wake-word ignored

**Decision**:
- [ ] PASS - State machine authority preserved
- [ ] FAIL - Any bypass potential, return to design

---

### ✅ Criterion 4: False Positives Are Silent

**Requirement**: False positives must NOT produce spoken messages (e.g., "Yes?" "Listening?").

**Checkpoints**:

- [ ] **4.1**: False positive → ambiguous input → "Please clarify" response
  - Evidence: Design section 5, FP strategy
  - Mechanism: False positive fire → THINKING state → empty LLM input → ambiguity handler
  - Result: User hears "Please clarify" (already existing behavior)
  - NOT spoken: No "Did you mean...?" or "Yes?" confirmation

- [ ] **4.2**: No confirmation state between detection and THINKING
  - Evidence: Architecture section 8
  - Design: Direct transition (LISTENING → THINKING, no intermediate)
  - Guarantee: No extra spoken message added

- [ ] **4.3**: False positive rate target is <5%
  - Evidence: Resource model section 4
  - Measurement: Will be measured before implementation
  - Tuning: Confidence threshold (0.85 proposed) adjustable

**Decision**:
- [ ] PASS - False positives are silent failures
- [ ] FAIL - Any spoken confirmation, return to design

---

### ✅ Criterion 5: PTT Always Wins

**Requirement**: Push-to-Talk cannot be blocked or delayed by wake-word.

**Checkpoints**:

- [ ] **5.1**: PTT pauses wake-word while SPACEBAR held
  - Evidence: Design section 2
  - Implementation: Listener paused during PTT active window
  - Result: No conflict between PTT audio and wake-word detection

- [ ] **5.2**: Wake-word does not queue behind PTT
  - Evidence: Priority matrix, case 2
  - Design: Wake-word events during PTT are discarded, not queued
  - Result: PTT processes, wake-word is lost (acceptable, PTT already active)

- [ ] **5.3**: PTT latency not impacted by wake-word
  - Evidence: Resource model <5% idle CPU, no shared resources
  - Guarantee: Lightweight detector runs independently
  - Test: PTT latency measured with/without wake-word active

**Decision**:
- [ ] PASS - PTT has absolute priority
- [ ] FAIL - Any PTT degradation, return to design

---

### ✅ Criterion 6: SLEEP Is Absolute

**Requirement**: Wake-word cannot wake a sleeping system.

**Checkpoints**:

- [ ] **6.1**: Wake-word listener is completely off in SLEEP state
  - Evidence: Design section 1
  - Mechanism: Listener process not started in SLEEP
  - Proof: Check design for SLEEP state → listener status
  - Expected: "Wake-word listener: DISABLED"

- [ ] **6.2**: SLEEP state unaffected by any utterance
  - Evidence: SLEEP matrix
  - Test: User says "ARGO" while asleep → no response
  - Test: User says "hello" → no response
  - Test: User says "wake up" via SPACEBAR PTT → transitions (only PTT works)

- [ ] **6.3**: Exit SLEEP requires PTT (SPACEBAR)
  - Evidence: Design section 1
  - Method 1: PTT + "wake up" command (future enhancement)
  - Method 2: System reboot
  - NOT allowed: Wake-word alone

**Decision**:
- [ ] PASS - SLEEP is absolute, unbreakable
- [ ] FAIL - Any sleep bypass, return to design

---

## Part 2: Resource Model Validation

### ✅ Criterion 7: CPU Usage Targets Met

**Requirement**: Wake-word must not degrade system performance.

**Checkpoints**:

- [ ] **7.1**: Idle CPU consumption <5%
  - Measurement: Run detector on idle system for 1 hour
  - Record: Max CPU %, average CPU %, memory usage
  - Pass threshold: Consistent <5%
  - Tool: Performance Monitor (Windows) or htop (Linux)

- [ ] **7.2**: Streaming latency unchanged with detector active
  - Measurement: TTS latency test with/without detector
  - Baseline: From Phase 7A-2 (time-to-first-audio ~800ms)
  - Pass threshold: <100ms difference (streaming latency degradation acceptable limit)
  - Evidence: Run same query 5 times, average latency

- [ ] **7.3**: Whisper PTT latency unchanged
  - Measurement: PTT recognition time with/without detector
  - Baseline: Expected ~1-2 seconds for typical query
  - Pass threshold: <200ms difference
  - Evidence: Hold SPACEBAR, speak 3-5 word query, measure time-to-response

- [ ] **7.4**: Memory footprint reasonable
  - Measurement: Memory usage of detector process
  - Pass threshold: <100MB (includes model, buffers, overhead)
  - Evidence: Top / Process Explorer

**Acceptance Gates**:
- [ ] CPU < 5%: Can proceed to implementation
- [ ] CPU 5-10%: Investigate optimization (lighter model?)
- [ ] CPU > 10%: FAIL - Must redesign or abandon wake-word

**Decision**:
- [ ] PASS - All resource targets met
- [ ] FAIL - Resource consumption too high, design review required

---

### ✅ Criterion 8: Detector Model Selected and Tested

**Requirement**: Lightweight keyword spotter must be chosen before coding.

**Checkpoints**:

- [ ] **8.1**: Detector model identified (e.g., TensorFlow Lite, etc.)
  - Evidence: Model name, source, license documented
  - Example: "TensorFlow Lite keyword spotter, 50MB footprint"
  - Record: Model repo, training data source

- [ ] **8.2**: "ARGO" keyword trained or validated
  - Evidence: Model tested on recordings of "ARGO"
  - Test set: 20+ true "ARGO" utterances, various speakers/accents
  - Pass threshold: >90% true positive rate on test set
  - False positive test: 1000+ negative samples (other words, noise)
  - Pass threshold: <5% false positive rate

- [ ] **8.3**: Confidence threshold determined (proposed 0.85)
  - Evidence: ROC curve or threshold analysis
  - Tuning: Threshold adjusted based on FP/TP trade-off
  - Pass threshold: ≥90% TP, ≤5% FP with chosen threshold

- [ ] **8.4**: Latency acceptable (target <200ms)
  - Measurement: Time from speech end to detection event
  - Test: 10 utterances of "ARGO", measure end-to-detection time
  - Pass threshold: All <200ms

**Decision**:
- [ ] PASS - Model selected, tested, metrics acceptable
- [ ] FAIL - Model not chosen or performance unacceptable, cannot proceed

---

## Part 3: Dependency and Integration Checks

### ✅ Criterion 9: No New External Dependencies

**Requirement**: Wake-word must not introduce heavy dependencies.

**Checkpoints**:

- [ ] **9.1**: No cloud service dependencies (no internet required)
  - Evidence: Detector runs locally only
  - Check: No API calls, no cloud sync
  - Guarantee: Works offline

- [ ] **9.2**: No additional Python packages beyond detector
  - Check: requirements.txt modifications
  - Allowed: Only lightweight detector library (TensorFlow Lite, etc.)
  - Not allowed: Full TensorFlow, Torch, heavy ML frameworks
  - Pass: <2 new dependencies

- [ ] **9.3**: No modification to Piper, Whisper, streaming
  - Evidence: Code review (should be zero changes to those modules)
  - Check: No patches to core/output_sink.py, wrapper/argo.py (streaming parts)
  - Pass: Streaming code untouched

- [ ] **9.4**: State machine modifications minimal
  - Evidence: Design shows no new states
  - Check: Only guards added, no state transitions invented
  - Pass: State machine API unchanged

**Decision**:
- [ ] PASS - No heavy dependencies added
- [ ] FAIL - Dependencies too heavy, return to design

---

### ✅ Criterion 10: Integration Points Clear

**Requirement**: Where and how wake-word integrates must be obvious.

**Checkpoints**:

- [ ] **10.1**: Listener startup point defined
  - Evidence: Design specifies when listener starts (LISTENING state)
  - Document: Where in code listener is spawned
  - Test: Listener starts exactly when state → LISTENING

- [ ] **10.2**: Listener shutdown point defined
  - Evidence: Design specifies when listener stops (any non-LISTENING state)
  - Document: Where listener is paused/killed
  - Test: Listener stops immediately on state change

- [ ] **10.3**: Event flow from detector → state machine clear
  - Evidence: How recognition event is communicated
  - Option 1: Function call with state machine lock
  - Option 2: Event queue (async-safe)
  - Document: Event flow diagram or pseudocode

- [ ] **10.4**: Error handling for detector crash defined
  - Evidence: Supervisor/restart logic
  - Document: What happens if detector dies, how it recovers

**Decision**:
- [ ] PASS - Integration points are clear
- [ ] FAIL - Integration unclear, return to design

---

## Part 4: Test Plan Acceptance

### ✅ Criterion 11: Test Plan Is Achievable

**Requirement**: Acceptance tests must be runnable and pass/fail criteria clear.

**Checkpoints**:

- [ ] **11.1**: Basic wake-word test (T1) is runnable
  - Precondition: System in LISTENING state (achievable)
  - Action: User says "ARGO" (measurable)
  - Expected: Transition to THINKING (observable in logs)
  - Pass/fail: Unambiguous

- [ ] **11.2**: PTT override test (T2) is runnable
  - Precondition: System in LISTENING, SPACEBAR ready (achievable)
  - Action: Hold SPACEBAR, say "ARGO" (measurable)
  - Expected: PTT wins, not wake-word (observable)
  - Pass/fail: Unambiguous

- [ ] **11.3**: STOP dominance test (T3) is runnable
  - Precondition: System accepting voice input (achievable)
  - Action: Speak "ARGO" then "STOP" (measurable)
  - Expected: STOP processes first, no transition (observable)
  - Pass/fail: Unambiguous

- [ ] **11.4**: SLEEP test (T4) is runnable
  - Precondition: System in SLEEP state (achievable)
  - Action: User says "ARGO" (measurable)
  - Expected: No response (observable)
  - Pass/fail: Unambiguous

**Decision**:
- [ ] PASS - All tests are runnable and clear
- [ ] FAIL - Tests ambiguous or not achievable, refine test plan

---

## Part 5: Design Review Sign-Off

### ✅ Criterion 12: No Hand-Waving Allowed

**Requirement**: If any part feels clever, uncertain, or "we'll figure it out later," design fails.

**Self-Assessment Questions** (Honest Answers Required):

- [ ] **12.1**: Can you explain wake-word behavior in STOP scenario without hesitation?
  - Expected answer: "STOP command cancels recognition event, clears audio buffer, returns to LISTENING"
  - Red flag: "Um, we'll handle that in testing" or "It should work out"

- [ ] **12.2**: Can you explain PTT override without ambiguity?
  - Expected answer: "Wake-word listener pauses while PTT active, resumes after"
  - Red flag: "PTT probably takes priority" or "We'll tune it later"

- [ ] **12.3**: Can you guarantee SLEEP is absolute without caveats?
  - Expected answer: "Listener is completely off in SLEEP state, no exceptions"
  - Red flag: "It should prevent false wakes" or "Mostly secure"

- [ ] **12.4**: Can you describe resource usage without hedging?
  - Expected answer: "<5% idle CPU, measured on reference hardware"
  - Red flag: "Probably low CPU" or "Should be fine"

- [ ] **12.5**: Can you list all edge cases without forgetting any?
  - Expected answer: [List all from WAKEWORD_DECISION_MATRIX.md]
  - Red flag: "I think we got most edge cases"

**Decision**:
- [ ] PASS - All answers are confident and specific
- [ ] FAIL - Any hand-waving detected, return to design

---

## Part 6: Final Gate Conditions

### ✅ Criterion 13: All Acceptance Criteria Above Met

**Prerequisite**: All checkpoints 1-12 must PASS before moving to implementation.

| Criterion | Status | Reviewer | Date |
|-----------|--------|----------|------|
| 1. Architecture fully specified | [ ] PASS [ ] FAIL | Bob | ____ |
| 2. STOP dominance unquestionable | [ ] PASS [ ] FAIL | Bob | ____ |
| 3. State machine not bypassed | [ ] PASS [ ] FAIL | Bob | ____ |
| 4. False positives silent | [ ] PASS [ ] FAIL | Bob | ____ |
| 5. PTT always wins | [ ] PASS [ ] FAIL | Bob | ____ |
| 6. SLEEP is absolute | [ ] PASS [ ] FAIL | Bob | ____ |
| 7. CPU targets met | [ ] PASS [ ] FAIL | Bob | ____ |
| 8. Detector selected & tested | [ ] PASS [ ] FAIL | Bob | ____ |
| 9. No new heavy dependencies | [ ] PASS [ ] FAIL | Bob | ____ |
| 10. Integration points clear | [ ] PASS [ ] FAIL | Bob | ____ |
| 11. Test plan achievable | [ ] PASS [ ] FAIL | Bob | ____ |
| 12. No hand-waving | [ ] PASS [ ] FAIL | Bob | ____ |

---

### ✅ Criterion 14: NO-GO Conditions (Auto-Fail)

**Any of these conditions → STOP, do NOT implement**:

- [ ] **NO-GO 1**: No lightweight detector model available
  - Implication: Cannot achieve <5% CPU idle
  - Decision: Abandon wake-word for this phase

- [ ] **NO-GO 2**: STOP latency increases >50ms with detector active
  - Implication: STOP dominance compromised
  - Decision: Abandon wake-word or redesign

- [ ] **NO-GO 3**: State machine must be heavily modified (>3 methods changed)
  - Implication: Architecture not clean
  - Decision: Return to design, simplify

- [ ] **NO-GO 4**: PTT latency degraded >200ms
  - Implication: Unacceptable performance impact
  - Decision: Lightweight detector not achievable, abandon phase

- [ ] **NO-GO 5**: False positive strategy requires spoken confirmation
  - Implication: Violates boring requirement
  - Decision: Return to design, find silent solution

- [ ] **NO-GO 6**: Wake-word design contains "maybe" or "probably"
  - Implication: Insufficient design rigor
  - Decision: Return to design, be more specific

---

## Part 7: Sign-Off and Gate

### Final Decision

**Phase 7A-3a Wake-Word Design Review:**

Date: __________  
Reviewer: Bob  

**Final Assessment:**

- [ ] **GO** - All criteria met, design is sound, implementation may proceed
- [ ] **NO-GO** - Criteria not met, return to design phase
- [ ] **NO-GO PERMANENT** - Abandon wake-word for this release

**Reviewer Notes**: ________________________________________________

**Criteria Failing (if NO-GO)**: ________________________________

**Next Action**:
- [ ] Proceed to Phase 7A-3b (Implementation)
- [ ] Return to design phase for revision
- [ ] Archive wake-word for future release

---

## Appendix: Design Documents Referenced

1. **PHASE_7A3_WAKEWORD_DESIGN.md** - Full architecture
2. **WAKEWORD_DECISION_MATRIX.md** - Decision tables
3. **PHASE_7A2_STREAMING_COMPLETE.md** - Streaming foundation (must not break)

---

*Checklist Complete*: 2026-01-18  
*Format*: GO/NO-GO gate for implementation  
*Audience*: Project manager, technical reviewer, implementer  
*Next*: Sign-off and implementation gate
