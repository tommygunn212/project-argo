# CORE STABILITY DECLARATION — v1.0.0-voice-core

**Date:** January 18, 2026  
**Status:** LOCKED AND STABLE  
**Audience:** All developers, future maintainers

---

## Foundation Files — LOCKED

These files are part of the v1.0.0-voice-core foundation and are locked from silent refactoring.

### Core Execution Engine

**File:** [wrapper/argo.py](wrapper/argo.py)

**Locked Sections:**
- State machine initialization and transitions (lines ~100-250)
- Voice mode parameter and memory skip logic (lines ~2603-2650)
- STOP interrupt handler (lines ~2700-2750)
- System prompt guardrail for voice mode (lines ~2800-2850)
- Main execution loop (run_argo function)

**What Can Change:**
- New command types (additive, not breaking)
- New voice mode options (must maintain statelessness)
- Performance optimizations (if STOP latency maintained <50ms)
- Logging improvements (additive only)

**What Cannot Change:**
- State machine transitions
- Memory skip in voice mode
- STOP interrupt authority
- System prompt priority structure

---

**File:** [core/output_sink.py](core/output_sink.py)

**Locked Sections:**
- Streaming architecture (_stream_audio_data() method)
- STOP authority during streaming
- Time-to-first-audio target (<1s)
- Non-blocking playback model

**What Can Change:**
- Buffer size tuning (if profiled)
- Frame reading optimization
- Sounddevice backend improvements
- Error handling enhancements

**What Cannot Change:**
- Blocking on full synthesis (must stay streaming)
- STOP latency increase
- Removal of profiling hooks

---

**File:** [wrapper/command_parser.py](wrapper/command_parser.py)

**Locked Sections:**
- Command parsing logic
- Priority rules (STOP > SLEEP > PTT > other)
- Guard conditions for valid transitions
- Error handling returns to LISTENING

**What Can Change:**
- New command types (additive)
- Improved help text
- Performance optimization

**What Cannot Change:**
- Priority rule order
- State guard conditions

---

### State Machine

**File:** [wrapper/state_machine.py](wrapper/state_machine.py) (if exists)

**Locked Sections:**
- State definitions (SLEEP, LISTENING, THINKING, SPEAKING)
- Valid transitions between states
- Guard conditions preventing invalid transitions
- <50ms transition latency requirement

**What Can Change:**
- Logging improvements
- Performance optimization
- New state metadata (if not changing transitions)

**What Cannot Change:**
- State definitions
- Valid transition paths
- Guard conditions

---

## Extensible Areas — OPEN FOR ADDITION

These areas are designed for extension without breaking foundation:

### Wake-Word Detector (Future Phase 7A-3)

**File:** [core/wake_word_detector.py](core/wake_word_detector.py) *(will be created)*

**Design Requirements (from Phase 7A-3a):**
- Listener only active in LISTENING state
- SPACEBAR (PTT) pauses wake-word
- STOP interrupts <50ms
- <5% idle CPU budget
- No state machine bypass
- Silent false positives (no confirmation messages)

**Integration Points:**
- State machine gates listener startup/shutdown
- Command parser has PTT override
- STOP handler kills detector process

---

### New Command Types

**Location:** [wrapper/command_parser.py](wrapper/command_parser.py)

**Addition Guidelines:**
- New command type extends valid_commands list
- Must define state transitions (which states allow this command?)
- Must define priority (where in STOP > SLEEP > PTT > other hierarchy?)
- Must handle errors by returning to LISTENING
- Priority rules locked (STOP always highest)

**Example (Future):**
```python
# New command type: ALARM
valid_commands = [..., 'alarm', ...]  # Additive

# Must define transitions
transitions['alarm'] = {
    'LISTENING': 'THINKING',  # Allow in LISTENING
    'SLEEP': None,  # Don't allow in SLEEP
    # etc.
}

# Must respect priority
command_priority = {
    'stop': 0,     # Highest
    'sleep': 1,
    'ptt': 2,
    'alarm': 3,    # New command
    # etc.
}
```

---

### New Intent Types

**Location:** [wrapper/argo.py](wrapper/argo.py) (or new module)

**Addition Guidelines:**
- New intent type added to switch/handler
- Must not bypass state machine
- Must have confirmation gate
- Must respect voice mode (stateless if voice_mode=True)
- Must log decisions for audit

---

### Tool Invocation (Future Phase 7E)

**File:** (TBD - will be new module)

**Design Requirements (Deferred):**
- Must have explicit confirmation gate
- Must have rollback procedures for state-changing actions
- Must not execute during SLEEP or without user approval
- Must log all executions for audit

---

### Voice Personality (Future Phase 7D)

**File:** (TBD - prompt engineering, no core changes)

**Design Requirements (Deferred):**
- Must not inject history into voice mode
- Must not change state machine
- Must not weaken STOP authority
- Prompt changes must respect priority layers

---

## How to Know If Your Change Is Safe

### ✅ SAFE TO MERGE (Will be approved)

- [ ] I added a new command type without changing existing state machine
- [ ] I optimized streaming buffer size and measured TTFA, it's still <1s
- [ ] I added new logging to the main loop without changing logic
- [ ] I improved error handling in command parser (additive, no existing paths removed)
- [ ] I tested STOP latency after my change, it's still <50ms
- [ ] I added a new intent type and tested voice mode is still stateless
- [ ] I added new help text without changing command parsing logic

### ⚠️ REQUIRES REVIEW (Will need discussion)

- [ ] I modified the state machine transitions
- [ ] I changed the command priority order
- [ ] I optimized STOP handler performance
- [ ] I refactored command parser internals (same behavior, different code)
- [ ] I added optional parameters to voice_mode that might affect statefulness

### ❌ WILL BE REJECTED (Stop here, discuss first)

- [ ] I want to remove the STOP interrupt handler
- [ ] I want to disable memory skip in voice mode for "better answers"
- [ ] I want to add background listening to detect wake-words
- [ ] I want to change the state machine transitions
- [ ] I want to refactor the whole voice mode system
- [ ] I removed the system prompt priority layers
- [ ] I made audio playback blocking again for simplicity

---

## PR Checklist for Locked Files

If your PR touches any locked file, include this checklist:

```markdown
## Stability Checklist (Locked Files)

- [ ] I have read CORE_STABILITY.md
- [ ] This change is additive, not breaking
- [ ] State machine transitions unchanged
- [ ] STOP latency still <50ms (if touching interrupt/audio)
- [ ] Voice mode still stateless (if touching voice or memory)
- [ ] SLEEP still blocks voice (if touching state machine)
- [ ] I measured the guarantee affected and it still holds
- [ ] I added tests for the guarantee
- [ ] I documented why this change respects the foundation

**Guarantee(s) Affected:**
- [ ] State machine authority
- [ ] STOP dominance (<50ms)
- [ ] Voice statelessness
- [ ] SLEEP absoluteness
- [ ] Prompt hygiene
- [ ] Streaming non-blocking

**Evidence:** [links to measurements, tests, or logs]
```

---

## Release Process for v1.0.0-voice-core

### What Happens on Each Release

1. **Test**: All tests must pass (existing + new)
2. **Measure**: All guarantees must still hold
   - STOP latency <50ms ✓
   - Voice mode stateless ✓
   - SLEEP blocks voice ✓
   - TTFA <1s ✓
   - CPU <5% idle (if wake-word active) ✓
3. **Review**: Locked file changes require explicit review
4. **Tag**: Create git tag with release notes
5. **Ship**: Push to GitHub and deploy

### What Cannot Be Changed After Release Tag

Once `v1.0.0-voice-core` is tagged:
- All 6 guarantees are locked
- No silent refactors of locked files
- No breaking changes without new major version
- Additive changes only (until next major version)

---

## Questions?

**Q: Can I optimize this locked file?**  
A: Yes, if the optimization doesn't break guarantees. Measure first, then propose with measurements.

**Q: Can I add a new feature to this locked file?**  
A: Yes, if it's additive and doesn't change existing behavior. Include tests.

**Q: Can I refactor the state machine?**  
A: Only if behavior is identical. Internal optimization is OK if transitions unchanged.

**Q: What if I find a bug in a locked file?**  
A: Fix it, but maintain the guarantee. Document the bug and fix in PR.

**Q: Can I change the priority of commands?**  
A: No. STOP > SLEEP > PTT is locked. Adding new commands is OK (additive).

**Q: What if the locked file has technical debt?**  
A: Improve it incrementally (additive changes, performance optimization). Refactoring requires careful review.

---

## Signed Stability Declaration

This declaration locks the foundation for v1.0.0-voice-core.

**By merging into main after this date, you accept:**

1. All 6 guarantees are non-negotiable
2. Locked files require explicit review for changes
3. Measurement and testing are required
4. Silent refactors will be rejected
5. Foundation must be maintained for all future releases

**Locked Date:** January 18, 2026  
**Locked By:** Bob (ARGO maintainer)  
**Timestamp:** 20:30 UTC

---

*The foundation is set. Build carefully on top of it.*
