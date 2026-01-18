# ARGO v1.4.5 Latency Framework - Quick Reference Card

## 🟢 STATUS: FRAMEWORK COMPLETE & INTEGRATED

All components in place. Ready for baseline measurement.

---

## 📊 8 Checkpoints (All Implemented)

```python
checkpoint("input_received")           # Start of request
checkpoint("transcription_complete")   # Whisper finished
checkpoint("intent_classified")        # Intent parsed
checkpoint("model_selected")           # Model chosen
checkpoint("ollama_request_start")     # Ollama request sent
checkpoint("first_token_received")     # First token back
checkpoint("stream_complete")          # Full response received
checkpoint("processing_complete")      # Post-processing done
```

---

## 🎚️ 3 Profiles (All Configured)

```
FAST  → First token ≤2s,  Total ≤6s,   Delays: 0ms   (Demo, emergency)
ARGO  → First token ≤3s,  Total ≤10s,  Delays: 200ms (Default, balanced)
VOICE → First token ≤3s,  Total ≤15s,  Delays: 300ms (Speech-paced)
```

**Set in .env:** `ARGO_LATENCY_PROFILE=ARGO`

---

## 📁 Key Files

| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| [runtime/latency_controller.py](runtime/latency_controller.py) | 221 | Core module | ✅ |
| [.env](.env) | 25 | Configuration | ✅ |
| [tests/test_latency.py](tests/test_latency.py) | 400+ | Tests (14 pass) | ✅ |
| [input_shell/app.py](input_shell/app.py) | 773 | Integrated | ✅ |

---

## 🧪 Test Status

```
pytest tests/test_latency.py -v
Result: 14 PASSED ✅, 4 SKIPPED (async), 0 FAILED ✅

python test_integration_latency.py
Result: 5/5 checks PASSED ✅
```

---

## 🚀 Quick Start

### Run Tests
```powershell
cd i:\argo
pytest tests/test_latency.py -v
python test_integration_latency.py
```

### Change Profile
```powershell
# Edit .env
ARGO_LATENCY_PROFILE=FAST    # or VOICE

# Restart app (picks up new profile)
python input_shell/app.py
```

### Read Latency Report
```
Look for log lines:
[LATENCY] input_received: 0ms
[LATENCY] processing_complete: 2850ms

Calculate deltas:
Total = processing_complete - input_received
```

---

## 📚 Documentation Map

| Guide | Purpose | Read Time |
|-------|---------|-----------|
| [README.md](README.md) | Overview + latency section | 5 min |
| [LATENCY_INTEGRATION_COMPLETE.md](LATENCY_INTEGRATION_COMPLETE.md) | Integration summary | 10 min |
| [LATENCY_SYSTEM_ARCHITECTURE.md](LATENCY_SYSTEM_ARCHITECTURE.md) | Technical deep dive | 20 min |
| [BASELINE_MEASUREMENT_QUICK_START.md](BASELINE_MEASUREMENT_QUICK_START.md) | How to measure | 15 min |
| [LATENCY_FILES_INDEX.md](LATENCY_FILES_INDEX.md) | File reference | 10 min |
| [LATENCY_COMPLETION_SUMMARY.md](LATENCY_COMPLETION_SUMMARY.md) | What was done | 10 min |

---

## ✅ Verification Checklist

- [x] latency_controller.py created (221 lines)
- [x] .env configuration file created
- [x] 8 checkpoints added to app.py
- [x] 4 endpoints instrumented
- [x] Regression tests passing (14/18)
- [x] Integration test passing (5/5)
- [x] No syntax errors in app.py
- [x] No missing imports
- [x] No inline sleeps (verified via grep)
- [x] Documentation complete (5 guides)

---

## 🎯 NEXT STEPS

### Phase 4: Baseline Measurement (NEXT)
1. Start app: `python input_shell/app.py`
2. Open UI: `http://localhost:8000`
3. Run 5 iterations × 4 scenarios
4. Extract checkpoint timings from logs
5. Fill measurements.csv

**Estimated time**: 30-60 minutes

See [BASELINE_MEASUREMENT_QUICK_START.md](BASELINE_MEASUREMENT_QUICK_START.md) for detailed instructions.

---

## 🔍 Troubleshooting

### App won't start
1. Check latency_controller.py exists in runtime/
2. Check .env exists in workspace root
3. Run tests: `pytest tests/test_latency.py`

### No checkpoint logs showing
1. Set `ARGO_LOG_LATENCY=true` in .env
2. Restart app
3. Check logs for `[LATENCY]` prefix

### Tests failing
```powershell
pytest tests/test_latency.py -v --tb=short
```

---

## 📊 Latency Budgets (Hard Limits)

### FAST Mode
```
First token: ≤ 2000ms (non-negotiable)
Total:       ≤ 6000ms (max response time)
Streams:     0ms delay (zero pacing)
```

### ARGO Mode
```
First token: ≤ 3000ms
Total:       ≤ 10000ms
Streams:     200ms delay (paced)
```

### VOICE Mode
```
First token: ≤ 3000ms
Total:       ≤ 15000ms
Streams:     300ms delay (slower pacing)
```

---

## 💻 API Reference

### Creating a Controller (Per-Request)
```python
from latency_controller import new_controller, checkpoint

controller = new_controller(latency_profile)
checkpoint("input_received")
```

### Applying Delays
```python
await controller.apply_stream_delay()  # Between chunks
await controller.apply_intentional_delay("tool_name", 500)  # Named delay
```

### Getting Report
```python
report = controller.report()
# {
#   "profile": "ARGO",
#   "elapsed_ms": 2345.0,
#   "checkpoints": {...},
#   "had_intentional_delays": True,
#   "exceeded_budget": False
# }
```

---

## 🎓 Key Principles

1. **No mystery delays** — All delays are explicit and logged
2. **FAST by default** — FAST mode has zero intentional delays
3. **Slow only on purpose** — Every delay has a reason
4. **Measurable everywhere** — 8 checkpoints track all time
5. **Async-safe** — Only asyncio.sleep, never time.sleep
6. **Budget-aware** — Delays skip if would exceed total budget
7. **Testable** — 18 regression tests prevent regressions
8. **Configurable** — Profile selection via .env

---

## 🔗 Integration Points

### /api/transcribe
```python
controller = new_controller(latency_profile)
checkpoint("input_received")
# ... transcribe audio ...
checkpoint("transcription_complete")
```

### /api/confirm-transcript
```python
controller = new_controller(latency_profile)
checkpoint("input_received")
# ... parse intent ...
checkpoint("intent_classified")
```

### /api/confirm-intent
```python
controller = new_controller(latency_profile)
checkpoint("input_received")
checkpoint("model_selected")
```

### /api/execute
```python
controller = new_controller(latency_profile)
checkpoint("input_received")
checkpoint("ollama_request_start")
# ... get response ...
checkpoint("first_token_received")
checkpoint("stream_complete")
checkpoint("processing_complete")
```

---

## 📈 Measurements Needed

**Baseline Collection Plan:**
- 5 runs per scenario (captures variance)
- 4 scenarios (text Q, text cmd, voice PTT, voice QA)
- 3 profiles (FAST, ARGO, VOICE)
- **Total: 60 data points minimum**

**Expected time**: 30-60 minutes of testing

---

## 🎯 Success Criteria

All achieved:
- ✅ Framework created and integrated
- ✅ 8 checkpoints added to correct locations
- ✅ 3 profiles configured and working
- ✅ Tests passing (14/18, 4 skip async)
- ✅ Zero inline sleeps verified
- ✅ Complete documentation
- ✅ Ready for baseline measurement

**Status: READY FOR NEXT PHASE** 🟢

---

## 📞 Contact & Support

For issues or questions:
1. Check [LATENCY_SYSTEM_ARCHITECTURE.md](LATENCY_SYSTEM_ARCHITECTURE.md) for technical details
2. Review [BASELINE_MEASUREMENT_QUICK_START.md](BASELINE_MEASUREMENT_QUICK_START.md) for measurement help
3. Check logs for `[LATENCY]` prefix entries
4. Run `pytest tests/test_latency.py -v` to verify framework

---

**Last Updated**: 2024  
**Version**: v1.4.5  
**Status**: 🟢 Framework Complete, Ready for Measurement

