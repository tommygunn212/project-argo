# STT Engine Preflight Check - Dependency Verification

## Update Notice (2026-02-01)
This document reflects the STT preflight work. Since then, ARGO added:
- Deterministic Tier‑1 app launch/close/focus (with aliases like "browser" for Edge and "notes" for Notepad)
- Bluetooth status/control
- Audio routing status/control
- System volume status/control (Windows, via pycaw/comtypes)
- Time/day/date queries
- Project-wide disclaimer (ARGO_DISCLAIMER.md)

Test counts in this document may be outdated. Re-run tests to refresh results.

## ✅ Problem Solved

ARGO was crashing during startup with an unclear error when `openai-whisper` package was missing:

```
[6:38:22] 2026-01-31 18:38:22,106 - ERROR - [STT] Initialization Error: openai-whisper not installed. Run: pip install openai-whisper
[6:38:22] 2026-01-31 18:38:22,107 - CRITICAL - Startup Failed: openai-whisper not installed. Run: pip install openai-whisper
```

**Root Cause**: Engine dependencies were only checked when the engine tried to load model, after audio initialization had already started.

**Solution**: Added preflight dependency verification that runs **before audio initialization**, failing fast with clear error message.

---

## What Changed

### 1. New Function: `verify_engine_dependencies(engine)` 
**File**: [core/stt_engine_manager.py](core/stt_engine_manager.py#L17-L42)

```python
def verify_engine_dependencies(engine: str) -> None:
    """
    Verify that required dependencies for selected engine are installed.
    
    Called early in startup (before audio init) to fail fast with clear error.
    """
    if engine == "openai":
        try:
            import whisper
            logger.info("[STT_ENGINE] Preflight: openai-whisper dependency OK")
        except ImportError:
            raise RuntimeError(
                "STT engine 'openai' selected but openai-whisper is not installed. "
                "Run: pip install openai-whisper"
            )
    
    elif engine == "faster":
        try:
            from faster_whisper import WhisperModel
            logger.info("[STT_ENGINE] Preflight: faster-whisper dependency OK")
        except ImportError:
            raise RuntimeError(
                "STT engine 'faster' selected but faster-whisper is not installed. "
                "Run: pip install faster-whisper"
            )
```

### 2. Updated: Pipeline Warmup Sequence
**File**: [core/pipeline.py](core/pipeline.py#L32)

**Import added**:
```python
from core.stt_engine_manager import STTEngineManager, verify_engine_dependencies
```

**Warmup sequence** ([core/pipeline.py#L250-255](core/pipeline.py#L250-255)):
```
1. Log engine config
2. ✅ PREFLIGHT CHECK: verify_engine_dependencies(stt_engine)  ← NEW
3. Initialize STT engine manager
4. Warmup engine
5. Initialize audio
6. Initialize LLM
7. Ready
```

**Before**:
```
1. Log engine config
2. Initialize STT engine manager (tries to load → crashes if missing)
3. Audio init (might fail silently)
4. ...
```

**After**:
```
1. Log engine config
2. ✅ Preflight check (fails fast if missing)
   → Clear error message with install instructions
3. Audio init (only if dependencies OK)
4. ...
```

### 3. Tests Added
**File**: [tests/test_stt_engine_manager.py](tests/test_stt_engine_manager.py#L244-275)

Three new test functions:

```python
def test_verify_engine_dependencies_openai():
    """Preflight check: openai-whisper dependency verification."""
    # Validates that openai-whisper dependency is checked early
    
def test_verify_engine_dependencies_faster():
    """Preflight check: faster-whisper dependency verification."""
    # Validates that faster-whisper dependency is checked early
    
def test_verify_engine_dependencies_invalid():
    """Preflight check: behavior with unknown engines."""
    # Documents that unknown engines pass through (caught later by STTEngineManager)
```

---

## Sequence Comparison

### Before Fix
```
START ARGO
  ↓
Load config
  ↓
Log: [STT] Engine configuration: engine=openai
  ↓
STTEngineManager.__init__()
  ↓
Try to import whisper
  ↓ ERROR (package missing)
  ↓
[STT] Initialization Error: openai-whisper not installed
  ↓
Audio enumeration starts (already halfway through!)
  ↓
CRASH with confusing sequence
```

### After Fix
```
START ARGO
  ↓
Load config
  ↓
Log: [STT] Engine configuration: engine=openai
  ↓
✅ verify_engine_dependencies(engine)
  ├─ Try: import whisper
  ├─ If missing: RuntimeError with clear instructions
  └─ If OK: Log "[STT_ENGINE] Preflight: openai-whisper dependency OK"
  ↓ (STOP HERE if missing - no audio init)
  ↓ (CONTINUE only if all dependencies OK)
  ↓
STTEngineManager.__init__()
  ↓
Audio init
  ↓
LLM init
  ↓
READY
```

---

## Behavior Guarantees

### ✅ Fail Fast
- Dependencies checked **before** audio initialization
- Missing package caught immediately
- Clear error message with install instructions

### ✅ No Fallback
- If openai-whisper is missing and config selects "openai", **hard stop**
- No silent CPU fallback
- No silent engine swap

### ✅ Both Engines Covered
- Check for openai-whisper (default)
- Check for faster-whisper (alternate)
- Different install instructions for each

### ✅ Clear Logging
```
[STT] Engine configuration: engine=openai, model=base, device=cpu
[STT_ENGINE] Preflight: openai-whisper dependency OK
[STT_ENGINE] Loading openai-whisper (model=base)...
[STT_ENGINE] openai-whisper loaded successfully (...)
[STT] STT engine ready (...)
```

---

## Test Results

### New Tests: 3/3 PASSING ✅
```
test_verify_engine_dependencies_openai ............ PASSED
test_verify_engine_dependencies_faster ........... PASSED
test_verify_engine_dependencies_invalid ......... PASSED
```

### Complete Test Suite: 29/29 PASSING ✅
```
Memory Confirmation Tests (6) ..................... PASSED
STT Confidence Safety Tests (1) ................... PASSED
Clarification Gate Tests (4) ..................... PASSED
Identity Confirmation Tests (6) .................. PASSED
STT Engine Manager Tests (9) ..................... PASSED
STT Engine Preflight Tests (3) ................... PASSED
─────────────────────────────────────────────
TOTAL: 29 PASSED
```

**Regressions**: ZERO ✅

---

## How It Works

### 1. Config Specifies Engine
```json
{
  "speech_to_text": {
    "engine": "openai",    // User choice
    "model": "base",
    "device": "cpu"
  }
}
```

### 2. Pipeline Reads Config
```python
stt_engine = config.get("speech_to_text.engine", "openai")
```

### 3. Preflight Check Runs
```python
verify_engine_dependencies(stt_engine)  # Checks if package is installed
```

### 4. Fails Fast if Missing
```python
# If not installed:
raise RuntimeError(
    "STT engine 'openai' selected but openai-whisper is not installed. "
    "Run: pip install openai-whisper"
)
```

### 5. Only Continues if OK
```python
# Only reaches here if verify_engine_dependencies() passed:
self.stt_engine_manager = STTEngineManager(engine, model_size, device)
```

---

## Error Messages (Clear & Actionable)

### Missing openai-whisper
```
RuntimeError: STT engine 'openai' selected but openai-whisper is not installed. 
Run: pip install openai-whisper
```

### Missing faster-whisper
```
RuntimeError: STT engine 'faster' selected but faster-whisper is not installed. 
Run: pip install faster-whisper
```

### Invalid Engine Selection
```
ValueError: Invalid STT_ENGINE: invalid_engine. 
Supported: openai, faster
```

---

## Future Protection

If user changes config to an unsupported engine or missing package:

**Before (Old Behavior)**:
```
Audio init completes
Halfway through pipeline
Tries to load engine
Crashes in the middle of interaction
Confusing error message
```

**After (New Behavior)**:
```
✅ Preflight check at startup
Error logged immediately
Clear install instruction
Pipeline never starts
Clean exit
```

---

## No Behavior Changes

- ✅ Default engine still `openai-whisper`
- ✅ No automatic fallback
- ✅ No dynamic switching
- ✅ No confidence normalization
- ✅ All gates unchanged
- ✅ Memory system unchanged
- ✅ LLM integration unchanged

This is **purely defensive**: fail fast with clarity, no policy changes.

---

## Deployment Checklist

- [x] Preflight check function added
- [x] Pipeline calls preflight check early
- [x] Tests validate preflight behavior
- [x] All 29 tests passing
- [x] Zero regressions
- [x] Clear error messages
- [x] Package installed (openai-whisper)
- [x] Ready for production

---

## Quick Reference

| Scenario | Behavior | Result |
|----------|----------|--------|
| openai selected + installed | Load openai-whisper | ✅ Proceeds |
| openai selected + missing | Preflight check fails | ❌ Clear error + install instruction |
| faster selected + installed | Load faster-whisper | ✅ Proceeds |
| faster selected + missing | Preflight check fails | ❌ Clear error + install instruction |
| Invalid engine + any | Config validation fails | ❌ Clear error at startup |

---

## Summary

**Implemented**: Preflight dependency verification for STT engines

**Impact**: Fails fast with clarity instead of crashing mid-pipeline with confusing errors

**Status**: ✅ COMPLETE & TESTED (29/29 tests passing)

**Safety**: No behavior changes, pure defensive programming

