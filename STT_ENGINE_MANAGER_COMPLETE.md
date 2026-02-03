# STT Engine Manager - Explicit Whisper Engine Selection

## Update Notice (2026-02-01)
This document reflects the STT engine manager work. Since then, ARGO added:
- Deterministic Tier‑1 app launch/close/focus (with aliases like "browser" for Edge and "notes" for Notepad)
- Bluetooth status/control
- Audio routing status/control
- System volume status/control (Windows, via pycaw/comtypes)
- Time/day/date queries
- Project-wide disclaimer (ARGO_DISCLAIMER.md)

Test counts in this document may be outdated. Re-run tests to refresh results.

## ✅ Implementation Complete

ARGO now explicitly knows which Whisper engine is being used and allows deterministic selection between them without changing behavior.

---

## What Was Implemented

### 1. STT Engine Manager (`core/stt_engine_manager.py`)
Central manager for explicit Whisper engine initialization and selection.

**Supported Engines:**
- `"openai"`: openai-whisper (original, default)
- `"faster"`: faster-whisper (optimized)

**Key Features:**
- No automatic fallback (explicit engine choice required)
- No dynamic switching (engine fixed at startup)
- Engine-native confidence returned as-is (no normalization)
- Uniform output contract for both engines

**Output Structure:**
```python
{
    "text": str,
    "confidence": float,  # Engine-native (not normalized)
    "segments": list,
    "engine": "openai" | "faster",
    "duration_ms": float
}
```

### 2. Configuration (`config.json.template`)
Added explicit STT engine selection to config:

```json
"speech_to_text": {
    "engine": "openai",
    "model": "base",
    "device": "cpu"
}
```

**Fields:**
- `engine`: Which Whisper to use (`"openai"` or `"faster"`)
- `model`: Model size (inherited from prior implementation)
- `device`: CPU or CUDA (inherited from prior implementation)

### 3. Pipeline Integration (`core/pipeline.py`)

**Initialization Changes:**
- Line 31: Import `STTEngineManager`
- Lines 84-85: Initialize `stt_engine_manager` and `stt_engine` attributes
- Lines 220-265: Load STT engine configuration explicitly

**Configuration Reading:**
```python
stt_engine = "openai"  # Default
if self._config is not None:
    stt_config = self._config.get("speech_to_text", {})
    stt_engine = stt_config.get("engine", "openai")
```

**Engine Validation:**
```python
if stt_engine not in STTEngineManager.SUPPORTED_ENGINES:
    raise ValueError(f"Invalid STT engine: {stt_engine}")
```

**Transcription Updates:**
- Lines 1020-1105: Use `STTEngineManager.transcribe()` instead of direct model call
- Capture and propagate engine name in metrics
- Log engine in timeline and broadcast

**Key Log Line:**
```
[STT] Engine configuration: engine=openai, model=base, device=cpu
[STT] engine=openai len=45 rms=0.1234 conf=0.85 1234ms
```

### 4. Test Suite (`tests/test_stt_engine_manager.py`)
9 comprehensive tests covering:

✅ Engine manager knows supported engines
✅ Invalid engine raises hard error (no fallback)
✅ Config includes engine field with default
✅ STT output includes engine name
✅ Engine logged in pipeline initialization
✅ No automatic fallback on device errors
✅ Metrics dictionary includes engine field
✅ Confidence not normalized (engine-native)
✅ Invalid engine caught at pipeline startup

---

## Safety Guarantees (Non-Negotiable)

### ✅ Default engine remains openai-whisper
```python
# config.json.template
"speech_to_text": {
    "engine": "openai"  # ← DEFAULT
}
```

### ✅ No automatic fallback
```python
# If engine choice is "faster" but faster-whisper not installed:
raise ImportError("faster-whisper not installed")
# → Hard error, NOT silent fallback to openai
```

### ✅ No dynamic switching
```python
# Engine locked at warmup time, never changes during session
self.stt_engine = stt_engine  # Set once, read many times
```

### ✅ No confidence normalization
```python
# Both engines return native confidence:
# - openai-whisper: log probability (negative values)
# - faster-whisper: log probability (negative values)
# → No rescaling to 0-1 range, no averaging, no smoothing
return {
    "confidence": confidence,  # Engine-native
}
```

### ✅ No LLM involvement
```python
# STT engine selection happens BEFORE pipeline.run_interaction()
# LLM never sees or affects engine choice
```

### ✅ Engine choice explicit and logged
```
[STT] Engine configuration: engine=openai, model=base, device=cpu
[STT_ENGINE] Loading openai-whisper (model=base)...
[STT_ENGINE] openai-whisper loaded successfully
[STT] Done in 1234ms (engine=openai): 'hello world'
```

### ✅ No behavior changes
```python
# All gates, thresholds, confidence logic remain unchanged:
# - Identity confirmation gate: still uses stt_conf ≥ 0.55
# - Clarification gate: still uses 0.35-0.55 range
# - No pipeline logic changes
# - No memory system changes
# - No LLM changes
```

---

## How It Works: Complete Flow

### Startup (one-time initialization)

```
1. config.json loaded
   ↓
2. speech_to_text.engine = "openai" extracted
   ↓
3. STTEngineManager(engine="openai", model="base", device="cpu") created
   ↓
4. whisper.load_model("base") called
   ↓
5. Dummy audio warmup run
   ↓
6. [STT] STT engine ready (engine=openai, ...)
```

### Runtime (per interaction)

```
1. Audio recorded
   ↓
2. pipeline.transcribe(audio_data) called
   ↓
3. self.stt_engine_manager.transcribe(audio_data) called
   ↓
4. Engine-specific transcription (openai or faster)
   ↓
5. Result includes "engine": "openai"
   ↓
6. [STT] Done in 1234ms (engine=openai): 'text'
   ↓
7. stt_metrics broadcast with engine field
   ↓
8. _last_stt_metrics includes engine for downstream gates
```

---

## Logging: Engine Visibility

### Initialization Logs
```
[STT] Engine configuration: engine=openai, model=base, device=cpu
[STT_ENGINE] Loading openai-whisper (model=base)...
[STT_ENGINE] openai-whisper loaded successfully
[STT] STT engine ready (engine=openai, model=base, device=cpu)
```

### Per-Interaction Logs
```
[STT] Starting transcription (engine=openai)... Audio len: 25600
[STT] Done in 1234ms (engine=openai): 'hello world'
STT_DONE engine=openai len=11 rms=0.0234 peak=0.5678 silence=0.12 conf=0.85
```

### Engine Selection Validation
```
[STT_ENGINE] Invalid STT_ENGINE: invalid. Supported: openai, faster
ValueError: Invalid STT engine: invalid
```

---

## Configuration Examples

### Use openai-whisper (default)
```json
{
  "speech_to_text": {
    "engine": "openai",
    "model": "base",
    "device": "cpu"
  }
}
```

### Switch to faster-whisper
```json
{
  "speech_to_text": {
    "engine": "faster",
    "model": "base",
    "device": "cuda"
  }
}
```

### Invalid engine (caught at startup)
```json
{
  "speech_to_text": {
    "engine": "invalid",
    "model": "base"
  }
}
```
**Result:**
```
ERROR [STT] Invalid STT_ENGINE: invalid. Supported: openai, faster
ValueError: Invalid STT engine: invalid
```

---

## Test Results: 9/9 Passing ✅

```
test_stt_engine_manager_supported_engines .................. PASSED
test_stt_engine_manager_rejects_invalid_engine ............. PASSED
test_config_includes_stt_engine ............................ PASSED
test_stt_result_includes_engine_field ...................... PASSED
test_stt_engine_explicit_in_pipeline_logs .................. PASSED
test_stt_no_automatic_fallback ............................ PASSED
test_stt_engine_in_metrics_broadcast ....................... PASSED
test_stt_confidence_not_normalized ......................... PASSED
test_invalid_engine_raises_on_pipeline_init ............... PASSED
```

---

## Future Engine Switching

Switching engines is now a one-line config change:

**From openai to faster:**
```json
"engine": "openai"  →  "engine": "faster"
```

**That's it.** No code changes, no behavior drift, no implicit adaptation.

---

## Why This Matters

### Problem Solved
Confusion about confidence numbers, debug visibility, reproducibility

### Solution
- ✅ Engine choice is **explicit** (no guessing)
- ✅ Engine is **logged** (clear audit trail)
- ✅ No **automatic fallback** (no silent engine swaps)
- ✅ No **confidence normalization** (engine-native values)
- ✅ No **behavior changes** (all gates untouched)

### Trust Comes From
Knowing **exactly** what ran, not assumptions.

---

## Code Files Modified

| File | Changes | Lines |
|------|---------|-------|
| `core/stt_engine_manager.py` | NEW file (engine manager) | 200+ |
| `core/pipeline.py` | Import, init, warmup, transcribe | ~100 |
| `config.json.template` | Added `"engine"` field | 1 |
| `tests/test_stt_engine_manager.py` | NEW test suite | 300+ |

---

## Validation Checklist

- ✅ Engine choice is explicit (config + code validation)
- ✅ Default remains openai-whisper (no breaking changes)
- ✅ Logs clearly show engine used (multiple tags)
- ✅ No behavior changes (all gates, thresholds unchanged)
- ✅ All tests still pass (9/9)
- ✅ Future engine swap is one-line config change
- ✅ No LLM involvement
- ✅ No implicit fallback
- ✅ No dynamic switching
- ✅ No confidence normalization

---

**Status**: COMPLETE & DEPLOYED ✅
**Tests**: 9/9 PASSING
**Behavior**: NO CHANGES (visibility only)
**Production Ready**: YES

This solves confusion about which Whisper engine is running without changing a single decision in the pipeline.
