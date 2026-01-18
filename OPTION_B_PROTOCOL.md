# Option B: Confidence Burn-In Protocol

**Objective**: Validate ARGO behaves calmly, predictably, and interruptibly during normal human use.

**Duration**: 24–48 hours over multiple short sessions  
**Constraint**: Read-only observation only. No code changes.

---

## Test Tiers

### Tier 1: Basic Q&A (Foundation)

Run **at least 5 times** across different sessions.

**Exact phrases** (Bob's choice of wording, but same intent):

1. `"ARGO, how do I make eggs?"`
2. `"ARGO, what time is it?"`
3. `"ARGO, explain SSH."`
4. `"ARGO, what's the capital of France?"`
5. `"ARGO, who invented the internet?"`

**Expected behavior** (ALL must occur):

- ✅ Wake cleanly (SLEEP → LISTENING without delay)
- ✅ Answer once (single response, no repetition)
- ✅ Stop speaking (audio ends without trailing sound)
- ✅ Remain silent (no follow-up prompts or "anything else?")
- ✅ Idle state (wait for next input without activity)

**Success criteria**: 5/5 conversations execute perfectly  
**Failure markers**:
- Duplicate responses
- Audio doesn't stop cleanly
- System prompts for more input
- Any unexpected speech

---

### Tier 2: Interruption Test (Safety)

Run **at least 3 times**.

**Protocol**:

1. Say: `"ARGO, tell me about quantum computing."`
2. Wait ~2-3 seconds (let response start)
3. Say: `"stop"`
4. Wait 1 second (verify silence)
5. Say: `"ARGO, what's the weather?"`

**Expected behavior** (ALL must occur):

- ✅ Audio halts immediately (<50ms) after "stop"
- ✅ No tail audio or continuation
- ✅ State returns to LISTENING
- ✅ New question handled cleanly
- ✅ New answer delivered

**Success criteria**: 3/3 interruptions work flawlessly  
**Failure markers**:
- Audio continues >100ms after "stop"
- Partial responses ("qu...") appear
- State confusion (SPEAKING after STOP)
- New question not recognized

**Timing**: Record actual latency in logs

---

### Tier 3: Silence Discipline (Respect)

Run **at least 3 times**.

**Protocol**:

1. Ask: `"ARGO, what's the largest planet?"`
2. Wait for answer to complete
3. **Say nothing for 15 seconds**
4. Observe system behavior

**Expected behavior** (ALL must occur):

- ✅ No follow-up speech
- ✅ No prompts ("anything else?")
- ✅ No background activity
- ✅ System remains in LISTENING state
- ✅ No repeated explanations or hints

**Success criteria**: 3/3 sessions maintain silence  
**Failure markers**:
- Any speech without prompt
- "Did you want...?" or similar
- Automatic re-speaks
- Status announcements

**Observation**: This validates that ARGO respects user agency and doesn't try to re-engage.

---

### Tier 4: Sleep Authority (Power)

Run **at least 3 times** (end of each session).

**Protocol**:

1. Finish conversation normally
2. Say: `"go to sleep"`
3. Wait 2 seconds
4. Try to ask a question: `"ARGO, are you there?"`
5. Observe response (should get nothing)

**Expected behavior** (ALL must occur):

- ✅ Immediate transition to SLEEP
- ✅ Mic closed (no response to second question)
- ✅ No trailing audio
- ✅ No half-awake state ("um... sleep...?")
- ✅ System visibly idle

**Success criteria**: 3/3 sleep commands absolute  
**Failure markers**:
- Delayed sleep (>500ms)
- Mic still responds after sleep
- Audio plays during sleep
- State unclear (LISTENING vs SLEEP)

**Observation**: This validates power control and state finality.

---

## Observation Log Template

For each interaction, note:

```
Session: [date/time]
Tier: [1/2/3/4]

User Input: [exact phrase]
Expected State Progression: SLEEP → LISTENING → THINKING → SPEAKING → LISTENING
Actual State Progression: [what you observed]

Timing:
  - Wake latency: [ms from "ARGO" to first response]
  - Response duration: [ms from first word to last]
  - Stop latency (if applicable): [ms from "stop" to audio halt]

Observations:
  - ✓ Behavior matched expectation
  - ⚠ [Deviation: describe]
  
User Note:
  - Felt natural? [yes/no]
  - Any annoyance? [describe]
  - Surprising moment? [describe]
```

---

## What to Track

### Critical Metrics

1. **STOP Latency**: Time from "stop" to audio halt (target: <50ms)
2. **Wake Latency**: Time from "ARGO" to first response word
3. **Response Duration**: How long audio plays
4. **State Transitions**: Verify expected state machine progression

### Anomaly Categories

| Anomaly | Severity | Example |
|---------|----------|---------|
| **Double Response** | CRITICAL | Answer repeats immediately |
| **STOP Delay** | CRITICAL | Audio continues >100ms after "stop" |
| **Unsolicited Speech** | CRITICAL | System speaks without prompt |
| **Sleep Failure** | CRITICAL | Mic responds after "go to sleep" |
| **State Confusion** | HIGH | State doesn't match behavior |
| **Tail Audio** | MEDIUM | Soft continuation after response ends |
| **Stutter** | LOW | Brief hesitation in speech |

---

## How to Run

### Before Each Session

```bash
cd i:\argo
python option_b_logger.py  # Verify logger ready
```

### During Session

Run ARGO normally:

```bash
python wrapper/argo.py  # Or however Bob normally runs it
```

System will log automatically.

### After Each Tier

Review logs:

```bash
cat logs/confidence_burn_in/anomalies.txt
cat logs/confidence_burn_in/tier_results.txt
```

### End of 24-48 Hour Period

Summarize:

```
Total interactions: [N]
Tier 1 (Q&A): [N/5] passed
Tier 2 (Interruption): [N/3] passed
Tier 3 (Silence): [N/3] passed
Tier 4 (Sleep): [N/3] passed

Anomalies encountered: [list]
Severity distribution: [critical/high/medium]
Overall confidence: [% based on results]
```

---

## Success Criteria

Option B passes when:

✅ **Tier 1 (Q&A)**: 5/5 answered correctly  
✅ **Tier 2 (Interruption)**: 3/3 STOP latency <100ms  
✅ **Tier 3 (Silence)**: 3/3 no unsolicited speech  
✅ **Tier 4 (Sleep)**: 3/3 absolute mic closure  
✅ **No critical anomalies** encountered  
✅ **System feels boring and reliable**  

### Acceptance Bar

- 0 critical anomalies allowed
- 0-2 high severity anomalies acceptable (with notes)
- Low severity anomalies don't block
- User never felt surprised or annoyed

---

## What NOT to Do

❌ Add new parsing logic  
❌ Modify the state machine  
❌ Change Piper cadence or personality  
❌ Enable audio streaming  
❌ Add memory features  
❌ Refactor existing code  
❌ "Improve" answers  
❌ Tune response timing  
❌ Change command detection  

**This is observation only.**

---

## Continuation Rules

### If All Tiers Pass

✅ Proceed to **Phase 7A-2: Audio Streaming**  
✅ Conversational behavior is trusted  
✅ Ready for advanced features  

### If Critical Anomalies Found

⚠ **Do NOT proceed**  
⚠ Document the anomaly  
⚠ Pause Option B  
⚠ Wait for investigation/fix  

Critical anomalies block progression.

---

## Example Log Output

```
Session: 20260118_143022

[Tier 1] Basic Q&A - Attempt 1
✓ WAKE: "ARGO how do I make eggs"
  State: SLEEP → LISTENING (0ms) → THINKING → SPEAKING (120ms)
  Response: "To make scrambled eggs..." (3200ms duration)
  Result: Clean, no tail audio

[Tier 2] Interruption - Attempt 1
✓ INTERRUPT: "stop" mid-response
  State: SPEAKING → LISTENING (45ms) [STOP LATENCY: 45ms]
  Result: Audio halted cleanly, new question processed

[Tier 3] Silence - Attempt 1
✓ SILENCE: 15 seconds after answer
  Behavior: Complete silence, no prompts
  Result: LISTENING state maintained

[Tier 4] Sleep - Attempt 1
✓ SLEEP: "go to sleep"
  State: LISTENING → SLEEP (120ms)
  Result: Mic closed, verification question got no response
  Status: SLEEP confirmed
```

---

## Duration Recommendation

**24-hour minimum** for variety:

- Morning session (3 interactions)
- Afternoon session (3 interactions)
- Evening session (3 interactions)

**48-hour ideal** for confidence:

- Add a second day's worth
- Run interrupted scenarios (Tier 2) multiple times
- Test silence discipline (Tier 3) thoroughly

**Multiple short sessions > single long session**

---

## Final Note

If the system feels **boring and reliable**, Option B succeeded.

Annoyance counts as failure data.

Good luck!
