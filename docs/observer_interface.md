# PHASE 16: OBSERVER INTERFACE (READ-ONLY VISIBILITY DASHBOARD)

## Goal

Provide **visibility without power**. A read-only dashboard for observing system state that cannot issue commands or mutate anything. Prevents "haunted appliance" syndrome where UI layer mysteriously changes behavior.

## Philosophy

### Why Read-Only?

The observer interface is **deliberately powerless**. It can:
- ✅ Read current state
- ✅ Display metrics
- ✅ Query history

But it **cannot**:
- ❌ Send voice commands
- ❌ Trigger wake words
- ❌ Control audio
- ❌ Modify system state

This separation is critical because:

1. **Prevents haunted appliance syndrome**: UI that observes cannot be mistaken for UI that controls
2. **Clear system boundaries**: Observer layer has zero control authority
3. **Easier to test**: Pure read functions are deterministic and safe
4. **Easier to secure**: No attack surface for command injection
5. **Easier to extend**: Future UI layers can safely layer on top without creating control loops

### What is "Haunted Appliance Syndrome"?

When an observer interface has even one small control capability (e.g., "I can stop the system"), it creates confusion:

- Developer: "The dashboard is just for viewing"
- User: "But I can press stop, so it's a control interface"
- Bugs emerge: "Why did pressing the button cause X?"
- Debugging gets hard: Observer layer can now cause side effects

**Solution**: Make observer strictly read-only. If you need controls, that's a different system (UI layer v2), not an observer.

---

## PHASE 16A: DATA TAP (Foundation)

### Module: `core/observer_snapshot.py`

Provides pure data extraction from Coordinator without mutation.

#### API

```python
def get_snapshot(coordinator) -> ObserverSnapshot:
    """
    Extract read-only snapshot from Coordinator.
    
    Pure function - reads state, never writes or mutates.
    
    Returns:
        ObserverSnapshot with current system state
    """
```

#### Data Captured

```
ObserverSnapshot {
    iteration_count: int              # Current iteration (1, 2, 3...)
    max_iterations: int               # Maximum allowed (usually 3)
    
    last_wake_timestamp: datetime     # When last wake word was detected
    last_transcript: str              # Last user utterance
    
    last_intent_type: str             # Last parsed intent (e.g., "QUESTION")
    last_intent_confidence: float     # Confidence score (0.0-1.0)
    
    last_response: str                # Last generated response text
    
    session_memory_summary: dict {
        capacity: int                 # Max recent interactions to store
        current_size: int             # How many are stored now
        total_appended: int           # Total ever appended
        recent_interactions: [
            (utterance, intent, response),
            ...
        ]
    }
    
    latency_stats_summary: dict {
        "total": {
            count: int
            min_ms: float
            max_ms: float
            avg_ms: float
            median_ms: float
        },
        "llm": { ... },
        "stt": { ... },
        ...
    }
}
```

#### Key Properties

- **Pure function**: No side effects, no logging, no imports from UI libraries
- **Deterministic**: Multiple calls with same coordinator produce identical results
- **Handles missing state**: Gracefully defaults if coordinator fields not set
- **Zero mutation**: Coordinator state unchanged after snapshot
- **JSON-exportable**: All data is primitive types (strings, numbers, lists, dicts)

#### Tests

File: `test_observer_snapshot.py`
- ✅ 10 unit tests, all passing
- Tests creation, export, extraction, mutation-prevention, determinism
- Mocks coordinator to avoid requiring live system

---

## PHASE 16B: CLI VIEW (TEXT ONLY)

### Script: `run_observer_cli.py`

Human-readable text display of coordinator state.

#### Usage

```bash
# Display observer snapshot and exit
python run_observer_cli.py
```

Output (example):

```
================================================================================
                    ARGO OBSERVER (READ-ONLY DASHBOARD)
================================================================================

ITERATION STATE
--------------------------------------------------------------------------------
  Current:  2
  Maximum:  3
  Progress: 67%

LAST INTERACTION
--------------------------------------------------------------------------------
  Wake Time:    15:30:45
  Transcript:   "what time is it"
  Intent:       QUESTION (85%)
  Response:     "It is currently 3 PM"

SESSION MEMORY
--------------------------------------------------------------------------------
  Capacity:     2 / 3 slots used
  Total added:  5
  Recent:       2 interaction(s)
    [1] "what is the time" -> "It is 3 PM"
    [2] "hello" -> "Hello there"

LATENCY STATISTICS
--------------------------------------------------------------------------------
  Total Time:   438ms avg
  Range:        411ms to 476ms
  Samples:      15

  Stage Breakdown:
    llm                211ms  ( 48.1%)
    stt                102ms  ( 23.4%)
    tts                 53ms  ( 12.0%)
    recording           50ms  ( 11.5%)
    parsing             10ms  (  2.3%)
    wake_to_record      12ms  (  2.7%)

================================================================================
               [LOCK] READ-ONLY OBSERVER (No controls, no state mutation)
================================================================================
```

#### Key Properties

- **ASCII-only**: Works in any terminal (no Unicode characters)
- **Runs once**: Displays snapshot and exits (no loops)
- **No fancy UI**: Plain text, no curses/colors/interactive elements
- **No control imports**: Cannot import InputTrigger, STT, OutputSink
- **Self-contained**: Gracefully handles missing coordinator (shows mock data)

#### Tests

File: `test_observer_cli.py`
- ✅ 7 smoke tests, all passing
- Verifies: runs/exits cleanly, displays all sections, no control imports
- Runs via subprocess to ensure clean separation

---

## PHASE 16C: DOCUMENTATION

### Why This Design?

#### Observer is Pure Read

**Decision**: Observer layer is **100% read-only**. No buttons, no commands, no triggers.

**Rationale**:
1. Clean separation of concerns (observation ≠ control)
2. Safe to extend (future UI layers won't accidentally gain control)
3. Easy to test (pure functions are deterministic)
4. Easy to audit (no hidden side effects)
5. Prevents "haunted appliance" syndrome

#### Why No Controls?

If observer could issue commands:
- It becomes a control interface, not just observer
- Testing becomes harder (need real coordinator)
- Security model becomes complex (who can control?)
- Debugging becomes hard (observer can cause side effects)

**Solution**: Observers are strictly read-only. If you need controls, create a separate command/control system.

#### Why No Voice?

Observer cannot:
- Trigger the wake word
- Start recording
- Issue commands to system

**Why**: These are control actions. Observer has zero control authority.

If you need voice control, that's a separate system that wraps the observer (e.g., a voice-controlled CLI layer on top of the observer).

#### Why No State Mutation?

Observer cannot:
- Modify coordinator state
- Clear memory
- Reset counters
- Change settings

**Why**: Mutations are side effects. Observer is side-effect-free.

#### Preventing "Haunted Appliance" Syndrome

**Problem**: When UI can both observe AND control, the system becomes "haunted" — mysterious behavior emerges.

Example:
- Dashboard shows "2 / 3 iterations complete"
- User presses "Stop" button
- System immediately stops
- Tomorrow, user wonders: "Did the system crash or did I press something?"

**Solution**: Make observation layer pure read-only. All control goes through a separate layer.

---

## Future UI Layers

If you want to build a UI that can control the system:

### Architecture (Recommended)

```
┌─────────────────────────────────────────┐
│         UI LAYER (Future)               │
│  - Command buttons                      │
│  - Voice control                        │
│  - Event triggers                       │
└─────────────────────────────────────────┘
                    ↓
        ┌───────────────────────────┐
        │  COMMAND/CONTROL SYSTEM   │
        │  (Must be separate layer) │
        └───────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│    OBSERVER INTERFACE (THIS PHASE)      │
│    - Read coordinator state             │
│    - Pure, deterministic                │
│    - Zero control authority             │
└─────────────────────────────────────────┘
                    ↓
        ┌───────────────────────────┐
        │     COORDINATOR v4        │
        │  (Voice orchestration)    │
        └───────────────────────────┘
```

### Important Rule

**Any UI that can issue commands is a different system** and requires a new task.

Do NOT try to add:
- ❌ "Stop" button to observer
- ❌ "Skip" command to observer
- ❌ "Wake up" trigger to observer
- ❌ "Clear memory" action to observer

These are control capabilities. The observer is read-only by design.

---

## Implementation Details

### Core Files

| File | Lines | Purpose |
|------|-------|---------|
| `core/observer_snapshot.py` | 170 | Pure data extraction |
| `run_observer_cli.py` | 220 | Text display |
| `test_observer_snapshot.py` | 200 | Unit tests (10 tests) |
| `test_observer_cli.py` | 100 | Smoke tests (7 tests) |
| `docs/observer_interface.md` | this file | Design rationale |

### Coordinator Changes

Modified `core/coordinator.py` to store last state for observation:

```python
# In __init__:
self._last_wake_timestamp = None
self._last_transcript = None
self._last_intent = None
self._last_response = None

# In on_trigger_detected callback:
self._last_wake_timestamp = datetime.now()
self._last_transcript = text
self._last_intent = intent
self._last_response = response_text
```

**Key**: These are purely for observation. Coordinator logic unchanged.

---

## Testing

### Snapshot Tests (test_observer_snapshot.py)

✅ 10 passing tests:
- Creation and export
- Data extraction accuracy
- Memory/latency inclusion
- Mutation prevention (coordinator unchanged)
- Determinism (multiple calls identical)
- Graceful handling of missing state

### CLI Tests (test_observer_cli.py)

✅ 7 passing tests:
- CLI runs and exits cleanly
- Displays all sections
- ASCII-safe output
- No control imports (InputTrigger, STT, OutputSink)
- Uses observer_snapshot correctly

### Coverage

- Data layer: 100% pure function tested
- CLI layer: 100% subprocess tested
- Integration: Manual testing with mock coordinator

---

## Usage

### For Developers

```python
from core.observer_snapshot import get_snapshot

# Get current state
snapshot = get_snapshot(coordinator)

# Export as dict
data = snapshot.to_dict()

# Access specific fields
print(f"Iteration: {snapshot.iteration_count}/{snapshot.max_iterations}")
print(f"Last transcript: {snapshot.last_transcript}")
print(f"Average latency: {snapshot.latency_stats_summary['total']['avg_ms']}ms")
```

### For Operators

```bash
# View live system state
python run_observer_cli.py

# Periodically refresh (every 5 seconds, e.g.)
while true; do python run_observer_cli.py; sleep 5; done
```

### For Future UI Layers

```python
from core.observer_snapshot import get_snapshot
from my_ui_framework import Dashboard

coordinator = ...  # Running coordinator

while True:
    snapshot = get_snapshot(coordinator)
    
    # UI reads snapshot
    dashboard.update(snapshot)
    
    # UI can display but NOT control
    # To control, create separate command layer
    time.sleep(0.5)
```

---

## Guarantees

### Observer Guarantees (Locked Forever)

1. **READ-ONLY**: Observer cannot modify coordinator state
2. **NO COMMANDS**: Observer cannot trigger wake, record, or control
3. **DETERMINISTIC**: Same coordinator → same snapshot (multiple times)
4. **PURE**: No side effects, no logging, no external I/O
5. **SAFE**: Zero risk of unexpected state changes

### Violations (Not Allowed)

These would violate the observer contract:

- ❌ `observer.stop_coordinator()` ← Command (not allowed)
- ❌ `observer.clear_memory()` ← Mutation (not allowed)
- ❌ `observer.trigger_wake()` ← Control (not allowed)
- ❌ `observer.log(...)` ← Side effect (not allowed)
- ❌ `observer.write_file(...)` ← I/O (not allowed)

If you need these, implement a command/control layer separately.

---

## References

- [Coordinator v4](../core/coordinator.py) - Orchestration layer
- [Session Memory](../core/session_memory.py) - Memory module
- [Latency Probes](../core/latency_probe.py) - Timing instrumentation
- [TASK 15 Documentation](../docs/latency_and_hardware.md) - Latency baseline

---

## Conclusion

**PHASE 16 Observer Interface is complete.**

We have:
- ✅ **Part A**: Pure snapshot extraction (`core/observer_snapshot.py`)
- ✅ **Part B**: CLI display (`run_observer_cli.py`)
- ✅ **Part C**: Design documentation (this file)
- ✅ **Tests**: 17 tests, all passing (10 unit + 7 smoke)

The observer is **deliberately read-only and powerless**. This is not a limitation—it's a security feature.

If you need to control the system, create a separate command layer. The observer will be ready to feed data to it.

---

**Status**: ✅ COMPLETE  
**Design**: LOCKED FOREVER (read-only, no mutations)  
**Ready for**: Production observation and future UI layers
