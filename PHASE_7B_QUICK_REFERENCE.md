# Phase 7B Quick Reference

## State Machine API

```python
from core.state_machine import State, StateMachine, get_state_machine

# Create instance
sm = StateMachine()

# Or get global instance
sm = get_state_machine()
```

### Commands

```python
# Wake from SLEEP
sm.wake()  # -> SLEEP to LISTENING (wake word "ARGO")

# Process command
sm.accept_command()  # -> LISTENING to THINKING

# Start audio
sm.start_audio()  # -> THINKING to SPEAKING

# Stop audio or natural end
sm.stop_audio()  # -> SPEAKING to LISTENING

# Sleep from any state
sm.sleep()  # -> ANY to SLEEP (command "go to sleep")
```

### State Checks

```python
# Current state
if sm.current_state == State.LISTENING:
    # Can process commands
    pass

# Predicates
if sm.is_asleep:
    # In SLEEP state
    pass

if sm.is_awake:
    # In any non-SLEEP state
    pass

if sm.is_listening:
    # In LISTENING state
    pass

if sm.is_thinking:
    # In THINKING state
    pass

if sm.is_speaking:
    # In SPEAKING state
    pass

# Check if listening is enabled
if sm.listening_enabled():
    # Can process voice commands
    pass
```

### Configuration

Set in .env or environment:

```env
WAKE_WORD_ENABLED=true      # Enable "ARGO" wake word (default: true)
SLEEP_WORD_ENABLED=true     # Enable "go to sleep" command (default: true)
```

### Callbacks

```python
def on_state_change(old_state, new_state):
    print(f"Transition: {old_state.value} -> {new_state.value}")

sm = StateMachine(on_state_change=on_state_change)
```

## State Transitions

Valid transitions (9 total):

1. SLEEP -> LISTENING (wake word "ARGO")
2. LISTENING -> THINKING (accept command)
3. THINKING -> SPEAKING (start audio)
4. SPEAKING -> LISTENING (stop or natural end)
5. LISTENING -> SLEEP (sleep word "go to sleep")
6. THINKING -> SLEEP (sleep word)
7. SPEAKING -> SLEEP (sleep word)

Invalid transitions: All other transitions are rejected safely.

## Testing

```bash
# Run all tests
python -m pytest test_state_machine.py -v

# Run specific test class
python -m pytest test_state_machine.py::TestWakeWord -v

# Run specific test
python -m pytest test_state_machine.py::TestWakeWord::test_wake_from_sleep -v
```

## Logging

All state transitions are logged:

```
INFO:core.state_machine:StateMachine initialized: SLEEP
INFO:core.state_machine:State transition: SLEEP -> LISTENING
```

Invalid transitions log warnings:

```
WARNING:core.state_machine:Invalid transition rejected: LISTENING -> SPEAKING
```

## Integration Points

### OutputSink Integration
```python
from core.output_sink import get_output_sink
from core.state_machine import get_state_machine

sm = get_state_machine()
sink = get_output_sink()

if sm.is_listening:
    # Process command and start audio
    sm.accept_command()
    sm.start_audio()
    sink.send(response_text, voice="amy")
    
    # When audio completes or stop is called
    sm.stop_audio()  # -> LISTENING
```

### Wrapper Integration (argo.py)
```python
from core.state_machine import get_state_machine

sm = get_state_machine()

# Wake word detected
if command == "ARGO":
    sm.wake()

# Process command only if listening
if sm.listening_enabled():
    process_command(command)

# Sleep command
if command == "go to sleep":
    sm.sleep()

# Stop command
if command == "stop":
    sm.stop_audio()
```

## Test Coverage

- 31 tests across 9 test classes
- 100% pass rate
- Coverage: All transitions, commands, configs, edge cases

Test classes:
- TestStateInitialization (4 tests)
- TestWakeWord (5 tests)
- TestSleepWord (5 tests)
- TestStopCommand (4 tests)
- TestNormalStateProgression (2 tests)
- TestInvalidTransitions (3 tests)
- TestStateCallbacks (3 tests)
- TestGlobalInstance (2 tests)
- TestConstraintCompliance (3 tests)

## Performance

- Wake latency: <10ms
- Sleep latency: <10ms
- Stop latency: <10ms (via OutputSink)
- Test execution: 31 tests in 0.08s

## Files

- core/state_machine.py - Implementation (325 lines)
- test_state_machine.py - Tests (440 lines, 31 tests)
- .env.example - Configuration flags
- PHASE_7B_COMPLETE.md - Detailed documentation
