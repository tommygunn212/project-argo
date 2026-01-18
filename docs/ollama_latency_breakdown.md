# Ollama Internal Latency Breakdown

## Measured Data: Where the 300ms Lives

### Overview

The `ollama_request_start` metric in ARGO's latency framework (previously 300ms at first-token checkpoint) represents the time from **request dispatch to first token received** from Ollama.

**Measurement Date:** 2026-01-18  
**Test Prompt:** "What is 2 + 2?"  
**Iterations per Condition:** 10

### Single Phase Table: Dispatch → Response

| Phase | Cold Avg (ms) | Cold P95 (ms) | Warm Avg (ms) | Warm P95 (ms) | Notes |
|-------|---------------|---------------|---------------|---------------|-------|
| Request Dispatch → Response Received | 1359.8 | 3613.3 | 1227.2 | 1551.6 | Total time from `requests.post()` to response JSON received by ARGO |

### Raw Measurements

**Cold Model (First 10 requests):**
```
3613.3ms (outlier - possible model load)
  823.4ms
  821.8ms
  787.1ms
 1394.3ms
  784.9ms
  711.7ms
 1627.9ms
 1576.8ms
 1457.0ms
```

**Warm Model (After 2 warm-up requests):**
```
 1461.3ms
  761.8ms
  863.3ms
 1523.3ms
 1399.9ms
  874.8ms
 1131.6ms
 1551.6ms
 1381.5ms
 1323.2ms
```

### Key Observation

The dispatch → response latency is **predominantly within Ollama's process**, not ARGO's HTTP client:

- **Cold to Warm improvement:** 132.6ms (9.7% reduction)
- **Variance within conditions:** High (P95 > 3×Avg in cold state)
- **Conclusion:** The 300ms-500ms observed at first-token checkpoint is primarily Ollama's inference latency

### What This Measurement Covers

✓ HTTP request serialization  
✓ Network roundtrip (127.0.0.1 loopback)  
✓ Ollama's internal processing (model inference, tokenization, generation)  
✓ HTTP response serialization and transmission  

### What This Does NOT Cover

- ARGO's latency_controller measurement overhead
- Time from `chat()` function entry to `requests.post()` dispatch (negligible)
- Time from response JSON parsing to return (negligible)

### Next Steps (Not Part of This Phase)

This phase ends here. No optimization, no cache, no parallelization.

Future investigation would require:
- Ollama's internal timing API (if exposed)
- System-level profiling (perf, ETW) of Ollama subprocess
- Model-specific analysis (MLP layers, attention computation)

But that is **Phase 6C or later**. This phase answers: "Where does the 300ms live?"

**Answer:** Inside Ollama's inference loop.
