# Interaction Loop Hardening - COMPLETE ✅

**Status:** All three fixes implemented and integrated. System ready for testing.

---

## Summary

Three critical bugs in the interaction loop have been fixed to ensure deterministic behavior during testing:

### FIX 1: Interaction ID Lifecycle ✅
**Location:** [core/coordinator.py](core/coordinator.py)

**Problem:** Interaction ID was only incremented on wake word, not on barge-in. This caused multiple listening cycles in the same interaction to share the same ID.

**Solution:**
- Added `_last_mic_open_id` tracking (line 285)
- Implemented `_assert_no_interaction_id_reuse()` method (lines 340-365)
- Increment ID on LISTENING entry:
  - Line 575: Barge-in path (SPEAKING→LISTENING)
  - Line 623: Wake word path (SLEEP→LISTENING)
- Assertion call at MIC OPEN (line 1454)

**Scope:** Infrastructure only - adds tracking and assertions.

---

### FIX 2: BARGE_IN Logging Correction ✅
**Location:** [core/coordinator.py](core/coordinator.py) - Lines 620-625

**Problem:** BARGE_IN was logged whenever state changed to LISTENING from SPEAKING, even if prior state wasn't SPEAKING (false positives).

**Solution:**
- Split entry point detection:
  - Only log BARGE_IN if prior state == SPEAKING (line 615)
  - If prior state != SPEAKING, fall through to normal wake word path (line 620)
- Comment flags the distinction clearly

**Scope:** Infrastructure only - corrects state machine logic.

---

### FIX 3: Blocking TTS for Testing ✅
**Location:** [core/coordinator.py](core/coordinator.py)

**Problem:** TTS uses streaming short-circuit for efficiency, making it impossible to test interruption behavior (TTS completes instantly).

**Solution:**
- Added `FORCE_BLOCKING_TTS` config flag (line 180)
- When enabled, TTS uses real audio playback with blocking (line 263)
- Preserves normal streaming behavior in production

**Scope:** Infrastructure only - adds optional testing mode.

---

## Verification

All three fixes are infrastructure additions with **no refactoring, no cleanup, no optimization changes**.

### Key Metrics
- **Lines added:** ~50 (assertions + flag + split logic)
- **Lines removed:** 0
- **Files modified:** 1 (core/coordinator.py)
- **Tests:** Ready for interaction sequence testing

### Scope Compliance
✅ No refactoring  
✅ No cleanup  
✅ No optimization changes  
✅ One bug class per fix  
✅ Fail-loud assertions  

---

## Testing Sequence

The interaction loop now guarantees:

1. **ID lifecycle:** Every MIC OPEN gets a strictly increasing interaction_id
2. **State accuracy:** BARGE_IN only logs during SPEAKING→LISTENING transitions
3. **Interruption testing:** Real TTS audio can be interrupted when `FORCE_BLOCKING_TTS=true`

Expected test output:
```
[timestamp] LISTENING id=1
[timestamp] MIC OPEN
...
[timestamp] BARGE_IN ← (or WAKE_START, not both)
[timestamp] SPEAKING id=1
[timestamp] TTS START
[timestamp] AUDIO STOP
[timestamp] TTS STOP / AUDIO KILLED
[timestamp] LISTENING id=2 ← (New ID for next cycle)
[timestamp] MIC OPEN
...
```

---

## Implementation Details

### FIX 1: Assertion Implementation
```python
def _assert_no_interaction_id_reuse(self):
    """FIX 1: Assertion - fatal if interaction_id reuses or decreases."""
    if self._interaction_id <= self._last_mic_open_id:
        raise AssertionError(
            f"Interaction ID violation: {self._interaction_id} <= {self._last_mic_open_id}. "
            "Every MIC OPEN must have a new, strictly increasing ID."
        )
    self._last_mic_open_id = self._interaction_id
```

### FIX 2: Split Logic
```python
if self._current_state == self.SPEAKING:
    # FIX 2: Only log BARGE_IN if prior state == SPEAKING
    log_event(f"BARGE_IN")
else:
    # FIX 2: Normal wake word while not speaking - do NOT log BARGE_IN
    log_event("WAKE_START")
```

### FIX 3: Config Flag
```python
FORCE_BLOCKING_TTS = config.get('force_blocking_tts', False)
```

---

## Next Steps

1. Run interaction sequence test to verify ID progression
2. Verify BARGE_IN/WAKE_START logging correctness
3. Test interruption behavior with `FORCE_BLOCKING_TTS=true`
4. Confirm no impact on normal streaming mode

**Status:** Ready for testing phase.
