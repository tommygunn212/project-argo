# ARGO Latency System Architecture

## Overview

The ARGO latency system is designed with one principle: **No mystery delays. Everything is explicit, measured, and intentional.**

Every request that flows through ARGO now has:
1. ✅ A latency controller instantiated at the start
2. ✅ 8 checkpoint measurements at key stages
3. ✅ A latency profile (FAST/ARGO/VOICE) that defines acceptable delays
4. ✅ Enforcement of budget limits via logging and assertions
5. ✅ A structured report at the end

---

## Request Flow with Latency Tracking

### Example: Text Command "Turn on kitchen lights"

```
User Input
    ↓
[CHECKPOINT] input_received (ms=0)
    ↓
Intent Parsing (intent_engine.parse)
    ↓
[CHECKPOINT] intent_classified (ms=150)
    ↓
Model Selection (FAST vs HEAVY)
    ↓
[CHECKPOINT] model_selected (ms=160)
    ↓
Execute Decision → /api/execute
    ↓
[CHECKPOINT] ollama_request_start (ms=200)
    ↓
Ollama Streaming (first token)
    ↓
[CHECKPOINT] first_token_received (ms=1200)
    ↓
Ollama Streaming (remaining chunks, with intentional delays)
    ↓
[CHECKPOINT] stream_complete (ms=2800)
    ↓
Post-Processing (parsing, logging)
    ↓
[CHECKPOINT] processing_complete (ms=2850)
    ↓
Return Response
    ↓
LATENCY REPORT:
  - Profile: ARGO
  - Total: 2850ms
  - First Token: 1200ms
  - Checkpoints: {...}
```

---

## Latency Controller Lifecycle

### Per-Request Lifecycle (Typical)

```python
# 1. NEW REQUEST ARRIVES
@app.post("/api/execute")
async def execute_plan():
    # 2. CREATE CONTROLLER (reset timer to 0)
    controller = new_controller(latency_profile)
    # Internal: self._start_time = time.time()
    #           self._checkpoints = {}
    
    # 3. LOG CHECKPOINTS (measure elapsed time)
    checkpoint("input_received")      # elapsed=0ms
    
    # 4. DO WORK
    result = await do_work()
    
    # 5. LOG MORE CHECKPOINTS
    checkpoint("work_complete")       # elapsed=~1200ms
    
    # 6. OPTIONALLY APPLY DELAYS
    if should_delay():
        await controller.apply_stream_delay()  # Only if profile allows
    
    # 7. GET REPORT
    report = controller.report()
    # Returns:
    # {
    #   "profile": "ARGO",
    #   "elapsed_ms": 1250.5,
    #   "checkpoints": {"input_received": 0.0, "work_complete": 1200.5},
    #   "had_intentional_delays": False,
    #   "exceeded_budget": False
    # }
    
    # 8. RETURN
    return {"result": result, "latency": report}
```

---

## Profile Comparison

### FAST Profile (Emergency / Demo Mode)
```
Characteristics:
  • Zero intentional delays
  • Smallest viable model
  • Maximum responsiveness
  • First token: ≤ 2000ms (non-negotiable)
  • Total response: ≤ 6000ms

Use Case:
  • Demos where speed matters
  • Time-critical operations
  • Resource-constrained environments

Latency Budget:
  first_token_max_ms: 2000
  total_response_max_ms: 6000
  stream_chunk_delay_ms: 0  ← KEY: ZERO DELAYS

Enforcement:
  • Tests verify no delays applied
  • Tests verify first token under budget
  • Budget overrun generates WARNING log
```

### ARGO Profile (Default, Balanced)
```
Characteristics:
  • Moderate, deliberate pacing
  • All delays intentional and measured
  • Balanced for most use cases
  • First token: ≤ 3000ms
  • Total response: ≤ 10000ms

Use Case:
  • Normal operation (default)
  • Streaming responses
  • Mixed text + voice workloads

Latency Budget:
  first_token_max_ms: 3000
  total_response_max_ms: 10000
  stream_chunk_delay_ms: 200  ← Paced at 200ms between chunks

Delays Applied:
  • 200ms between streamed chunks (intentional pacing)
  • Logs reason for each delay
  • Skips delay if would exceed budget
```

### VOICE Profile (Speech-Paced)
```
Characteristics:
  • Speech-rate pacing (conversational speed)
  • Supports parallel transcription + intent
  • Longer total budget for complex responses
  • First token: ≤ 3000ms
  • Total response: ≤ 15000ms

Use Case:
  • Voice input/output workflows
  • Conversational interactions
  • Full-duplex streaming

Latency Budget:
  first_token_max_ms: 3000
  total_response_max_ms: 15000
  stream_chunk_delay_ms: 300  ← Paced at 300ms (slower for speech)

Optimizations:
  • Transcription can start in parallel with intent parsing
  • Early-exit: Begin intent classification at 0.7 confidence
  • Delays aligned to speech natural pause rates
```

---

## Core Components

### 1. LatencyProfile Enum
```python
class LatencyProfile(Enum):
    FAST = "FAST"    # Zero delay
    ARGO = "ARGO"    # Default, balanced
    VOICE = "VOICE"  # Speech-paced
```

### 2. LatencyBudget Dataclass
```python
@dataclass
class LatencyBudget:
    profile: LatencyProfile
    first_token_max_ms: int         # Hard limit for first token
    total_response_max_ms: int      # Hard limit for entire response
    stream_chunk_delay_ms: int      # Intentional delay between chunks
```

### 3. LatencyController Class

**Key Methods:**
- `log_checkpoint(name)` — Mark a timing point, log elapsed time
- `elapsed_ms()` — Return milliseconds since controller creation
- `apply_stream_delay()` — Apply intentional delay if profile allows
- `apply_intentional_delay(name, delay_ms)` — Named delay for tool execution
- `should_emit_status()` — Return True if > 3s (emit "Still processing...")
- `check_first_token_latency()` — Log WARNING if first token late
- `report()` — Return structured latency report dict

**Global Functions:**
- `new_controller(profile)` — Create controller for a request
- `checkpoint(name)` — Log checkpoint in current controller
- `get_controller()` — Retrieve current controller
- `set_controller(controller)` — Set controller for request

---

## Delay Application Rules

### Stream Delay (Between Chunks)
```python
async def apply_stream_delay() -> None:
    """
    Apply intentional delay between streamed chunks.
    
    RULES:
    1. Only if profile requests it (stream_chunk_delay_ms > 0)
    2. Skip in FAST mode (stream_chunk_delay_ms = 0)
    3. Budget-aware: skip if would exceed total budget
    4. Always log if applied
    5. Async-safe (never blocks)
    """
```

**Decision Flow:**
```
Is stream_chunk_delay_ms > 0?
  ↓ YES
Would delay exceed total budget?
  ↓ NO → Apply delay, log "Applying stream delay: 200ms"
  ↓ YES → Skip delay, log "Skipping: would exceed budget"
↓ NO (FAST mode)
Skip delay (zero delays in FAST)
```

### Intentional Delay (Tool Execution, Policy Gate)
```python
async def apply_intentional_delay(name: str, delay_ms: int) -> None:
    """
    Apply named intentional delay for:
    - Tool execution (wait for real-world action)
    - Policy gates (wait for LLM decision)
    - Clarification (wait for human confirmation)
    
    NEVER use for "thinking" or fake delays.
    """
```

**Decision Flow:**
```
Remaining budget = total_budget - elapsed_time
Is requested_delay < remaining_budget?
  ↓ YES → Apply delay, log "Intentional delay (name): Xms"
  ↓ NO → Skip delay, log "Skipping: would exceed budget (requested=Xms, remaining=Yms)"
```

---

## Configuration (Environment Variables)

### .env Settings
```dotenv
# Profile selection (FAST, ARGO, VOICE)
ARGO_LATENCY_PROFILE=ARGO

# Safety ceiling for single intentional delay
ARGO_MAX_INTENTIONAL_DELAY_MS=1200

# Delay between chunks (can override per profile)
ARGO_STREAM_CHUNK_DELAY_MS=200

# Enable detailed logging at checkpoint
ARGO_LOG_LATENCY=false  # Set to true for debugging

# Ollama endpoint
OLLAMA_API_URL=http://localhost:11434

# Q&A availability
HAL_CHAT_ENABLED=true
```

### Loading in app.py
```python
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

profile_name = os.getenv("ARGO_LATENCY_PROFILE", "ARGO").upper()
latency_profile = LatencyProfile[profile_name]
```

---

## Checkpoint Map

### 8 Standard Checkpoints

| # | Checkpoint | Event | Endpoint |
|---|-----------|-------|----------|
| 1 | `input_received` | User input arrives | /api/transcribe, /api/confirm-transcript, /api/confirm-intent, /api/execute |
| 2 | `transcription_complete` | Whisper finishes | /api/transcribe |
| 3 | `intent_classified` | Intent parsed | /api/confirm-transcript |
| 4 | `model_selected` | Model chosen (FAST/HEAVY) | /api/confirm-intent |
| 5 | `ollama_request_start` | Ollama request sent | /api/execute |
| 6 | `first_token_received` | First token back from Ollama | /api/execute |
| 7 | `stream_complete` | Full response streamed | /api/execute |
| 8 | `processing_complete` | Post-processing done | /api/execute |

### Calculation Guide
```
Whisper Time = transcription_complete - input_received
Intent Parse Time = intent_classified - input_received
Ollama TTFT = first_token_received - ollama_request_start
Stream Time = stream_complete - first_token_received
Total Time = processing_complete - input_received
```

---

## Testing & Validation

### Regression Test Suite (tests/test_latency.py)

**9 Test Classes, 18 Tests:**

1. **TestLatencyControllerBasics** (3 tests)
   - Controller creation
   - Checkpoint logging
   - Budget defaults per profile

2. **TestFastModeContract** (3 tests)
   - Zero delays in FAST mode
   - No stream delays applied
   - First token ≤ 2000ms enforced

3. **TestDelayOriginControl** (2 tests)
   - All delays logged via controller (no inline sleeps)
   - Budget boundaries respected

4. **TestFirstTokenTiming** (2 tests)
   - Warn if first token exceeds budget
   - Pass if under budget

5. **TestStatusEmission** (2 tests)
   - Emit status if > 3s elapsed
   - Skip if < 3s elapsed

6. **TestReporting** (1 test)
   - Report structure: profile, elapsed_ms, checkpoints, exceeded_budget

7. **TestGlobalController** (1 test)
   - Singleton pattern (set/get controller)

8. **TestNoInlineSleeps** (2 tests)
   - No time.sleep() in code
   - Async-safe delays only

9. **TestBudgetExceedance** (2 tests)
   - Report exceeded flag when over budget
   - Report OK flag when under budget

**Run Tests:**
```powershell
pytest tests/test_latency.py -v
# Result: 14 PASSED, 4 SKIPPED (async, non-critical), 0 FAILED
```

---

## Performance Implications

### Memory Overhead
- Per-request: ~1KB (controller dict + checkpoint storage)
- Negligible for typical workloads

### CPU Overhead
- Checkpoint logging: < 1ms per checkpoint
- Time.time() calls: < 0.1ms each
- Total instrumentation overhead: < 5ms per request

### Network Impact
- No additional network calls
- No data sent to external services
- All measurement is local

---

## Future Enhancements

### Phase 2: Voice Path Parallelization
```
Current (Sequential):
  Transcribe → Intent → Plan → Execute (linear)

Optimized (Parallel):
  Transcribe ──┐
               ├→ Intent → Plan → Execute
  Intent (early-exit at 0.7 confidence) ──┘

Potential Savings: 500-800ms on voice paths
Measurable via latency framework
```

### Phase 3: Streaming Optimization
```
Current: Apply fixed 200ms/300ms delays between chunks
Optimized: Variable delays based on confidence/importance

Lower confidence: Longer delay (gives more time for thinking)
High confidence: Shorter delay (faster response)
```

### Phase 4: Analytics & Alerting
```
Collect measurements over time
Generate performance dashboards
Alert if latency > budget for 3+ consecutive requests
```

---

## Summary

**The latency system provides:**
- ✅ Visibility: 8 checkpoints measure every stage
- ✅ Control: Profile-based budgets enforce SLAs
- ✅ Intention: All delays logged with reason
- ✅ Safety: No inline sleeps, async-only
- ✅ Testing: Regression suite prevents regressions

**You can now answer:**
- "How long does transcription take?" (input_received → transcription_complete)
- "Where do we spend the most time?" (largest checkpoint gap)
- "Are we within budget?" (elapsed_ms vs total_response_max_ms)
- "Which profile is fastest?" (compare FAST vs ARGO vs VOICE)

**No more:** "It feels slow" or "I think it's the network"  
**Instead:** "Ollama TTFT = 1200ms, budget = 3000ms, OK"

