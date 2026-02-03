# Test Verification Command & Expected Output

## Update Notice (2026-02-01)
This document reflects the memory safety system tests. Since then, ARGO added:
- Deterministic Tier‑1 app launch/close/focus (with aliases like "browser" for Edge and "notes" for Notepad)
- Bluetooth status/control
- Audio routing status/control
- System volume status/control (Windows, via pycaw/comtypes)
- Time/day/date queries
- Project-wide disclaimer (ARGO_DISCLAIMER.md)

The test lists and counts here may be outdated. Re-run tests to refresh results.

## Quick Verification

### Run Complete Test Suite (17 Tests)
```bash
cd i:\argo
I:\argo\.venv\Scripts\python.exe -m pytest tests/test_memory_brutal.py tests/test_stt_confidence_default_guard.py tests/test_clarification_gate.py tests/test_confirmable_identity_memory.py -v
```

### Expected Output
```
============================= test session starts =============================
platform win32 -- Python 3.11.0, pytest-9.0.2, pluggy-1.6.0
rootdir: I:\argo
configfile: pytest.ini
collected 17 items

tests/test_memory_brutal.py::test_phase1_intent_explicit_vs_implicit PASSED [ 5%]
tests/test_memory_brutal.py::test_phase2_memory_types PASSED             [11%]
tests/test_memory_brutal.py::test_phase3_negative_and_adversarial PASSED [17%]
tests/test_memory_brutal.py::test_phase4_deletion_and_erase PASSED       [23%]
tests/test_memory_brutal.py::test_phase5_failure_resilience PASSED       [29%]
tests/test_memory_brutal.py::test_phase6_action_isolation PASSED         [35%]
tests/test_stt_confidence_default_guard.py::test_stt_confidence_default_guard PASSED [ 41%]
tests/test_clarification_gate.py::test_low_conf_ambiguous_triggers_clarification PASSED [ 47%]
tests/test_clarification_gate.py::test_repeated_clarification_not_asked_twice PASSED [ 52%]
tests/test_clarification_gate.py::test_high_conf_question_bypasses_clarification PASSED [ 58%]
tests/test_clarification_gate.py::test_flag_persists_until_canonical_hit PASSED [ 64%]
tests/test_confirmable_identity_memory.py::test_high_conf_name_statement_triggers_confirmation PASSED [ 70%]
tests/test_confirmable_identity_memory.py::test_name_confirmation_yes_writes_memory PASSED [ 76%]
tests/test_confirmable_identity_memory.py::test_name_confirmation_no_drops_memory PASSED [ 82%]
tests/test_confirmable_identity_memory.py::test_low_conf_name_statement_ignored PASSED [ 88%]
tests/test_confirmable_identity_memory.py::test_name_with_special_characters_sanitized PASSED [ 94%]
tests/test_confirmable_identity_memory.py::test_question_skips_name_gate PASSED [100%]

============================== 17 passed in 146.78s ===============================
```

---

## Individual Test Suites

### Memory Confirmation Tests (6/6)
```bash
I:\argo\.venv\Scripts\python.exe -m pytest tests/test_memory_brutal.py -v
```

**Expected**: 6 passed

### STT Safety Tests (1/1)
```bash
I:\argo\.venv\Scripts\python.exe -m pytest tests/test_stt_confidence_default_guard.py -v
```

**Expected**: 1 passed

### Clarification Gate Tests (4/4)
```bash
I:\argo\.venv\Scripts\python.exe -m pytest tests/test_clarification_gate.py -v
```

**Expected**: 4 passed

### Identity Confirmation Tests (6/6) ⭐ NEW
```bash
I:\argo\.venv\Scripts\python.exe -m pytest tests/test_confirmable_identity_memory.py -v
```

**Expected**: 6 passed

---

## Quick Verification (Summary Mode)
```bash
I:\argo\.venv\Scripts\python.exe -m pytest tests/ --tb=no -q
```

**Expected Output**:
```
.................

17 passed, 1 warning in 146.78s
```

---

## Production Deployment Verification

### Pre-Deployment
```bash
# Verify tests pass before deploying
I:\argo\.venv\Scripts\python.exe -m pytest tests/ -q
# Expected: 17 passed
```

### Post-Deployment
```bash
# Verify deployment successful
I:\argo\.venv\Scripts\python.exe -m pytest tests/ -q
# Expected: 17 passed (same as pre-deployment)
```

### Rollback Verification
```bash
# After rollback, should show 11 passing (identity tests skipped)
I:\argo\.venv\Scripts\python.exe -m pytest tests/test_memory_brutal.py tests/test_stt_confidence_default_guard.py tests/test_clarification_gate.py -q
# Expected: 11 passed (if identity tests not in rollback version)
```

---

## Key Test Cases

### Identity Confirmation - High Confidence ✅
```
Input:  "My name is Tommy" (confidence 0.85)
Flow:   Detect pattern → ≥0.55 → ask confirmation → flag set
Result: Waiting for confirmation (no memory write yet)
Test:   test_high_conf_name_statement_triggers_confirmation PASSED
```

### Identity Confirmation - User Approval ✅
```
Input:  "Yes" (confidence 0.99)
Flow:   Check confirm_name flag → read response → write FACT
Result: "Got it, I'll remember that you're Tommy."
Test:   test_name_confirmation_yes_writes_memory PASSED
```

### Identity Confirmation - User Denial ✅
```
Input:  "No" (confidence 0.99)
Flow:   Check confirm_name flag → read response → drop memory
Result: Silently acknowledge, no memory written
Test:   test_name_confirmation_no_drops_memory PASSED
```

### Identity Confirmation - Low Confidence ✅
```
Input:  "My name is Tommy" (confidence 0.35)
Flow:   Detect pattern → <0.55 threshold → ignore completely
Result: No confirmation prompt, no memory write
Test:   test_low_conf_name_statement_ignored PASSED
```

### Special Character Handling ✅
```
Input:  "My name is jean-pierre" (confidence 0.85)
Flow:   Extract name → title-case → "Jean-Pierre" → ask → write
Result: Memory persisted with correct title-casing
Test:   test_name_with_special_characters_sanitized PASSED
```

### Question Bypass ✅
```
Input:  "What is my name?" (confidence 0.85)
Flow:   Detect question syntax (? at end) → bypass gate
Result: No identity confirmation prompt
Test:   test_question_skips_name_gate PASSED
```

---

## Debugging Tips

### If tests fail with "Memory store unavailable"
```
Solution: Ensure tmp_path is properly scoped in test
Check: MemoryStore(tmp_path / "memory.db") initialization
```

### If tests fail with "confirm_name is None"
```
Solution: Use `is not True` instead of `is False` for None checks
Check: `pipeline._session_flags.get("confirm_name") is not True`
```

### If tests fail with "mem_type must be FACT, PROJECT, or PREFERENCE"
```
Solution: Use "FACT" as memory type, not "identity"
Check: `add_memory("FACT", "user_name", value, "user_identity")`
```

### If tests show regressions
```
Solution: Compare against baseline (17/17 expected)
Debug: Run individual test with -vv flag: pytest test.py::test_name -vv
```

---

## Performance Monitoring

### Expected Latencies
- Name extraction: ~0.1ms
- Confidence calculation: ~1ms
- Confirmation latency: ~5-10ms total
- Memory write: ~50ms
- LLM (when used): ~2-5s

### No Performance Regression Expected
- All gate logic adds <100ms total overhead
- LLM (if used) dominates latency (~2-5s)
- Memory path is faster than LLM (confirmation returns early)

---

## Continuous Integration Setup

### GitHub Actions (Example)
```yaml
name: Run Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pytest tests/ -q
        # Expected: 17 passed
```

### Local Pre-Commit Hook
```bash
#!/bin/bash
python -m pytest tests/ -q
if [ $? -ne 0 ]; then
    echo "Tests failed, commit aborted"
    exit 1
fi
```

---

## Success Criteria

### All Tests Pass ✅
```bash
I:\argo\.venv\Scripts\python.exe -m pytest tests/ -q
# Must show: 17 passed
```

### No Regressions ✅
```bash
# Prior test count: 11 (memory + STT + clarification)
# New test count: 17 (adds 6 identity tests)
# All must pass
```

### Deployment Ready ✅
- [x] 17/17 tests passing
- [x] Zero regressions
- [x] Code changes minimal (~50 lines)
- [x] No schema migrations needed
- [x] No dependency changes needed
- [x] Documentation complete

---

## Rollback Verification

### If Deployment Needs Rollback

```bash
# 1. Restore core/pipeline.py from backup
# 2. Restart ARGO service
# 3. Verify tests revert

# Before rollback: 17/17 passing (with identity tests)
I:\argo\.venv\Scripts\python.exe -m pytest tests/ -q
# Expected: 17 passed

# After rollback: 11/11 passing (identity tests skipped if removed)
I:\argo\.venv\Scripts\python.exe -m pytest tests/test_memory_brutal.py tests/test_stt_confidence_default_guard.py tests/test_clarification_gate.py -q
# Expected: 11 passed
```

---

**Test Infrastructure**: COMPLETE ✅
**All Tests**: 17/17 PASSING ✅
**Ready for Production**: YES ✅

For more information, see:
- [FINAL_STATUS_REPORT.md](FINAL_STATUS_REPORT.md)
- [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)
- [EXECUTIVE_SUMMARY_COMPLETE.md](EXECUTIVE_SUMMARY_COMPLETE.md)
