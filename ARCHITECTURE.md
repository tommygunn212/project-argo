# ARGO Architecture

## System Overview

ARGO is a 7-layer voice system designed for predictability, debuggability, and control.

```
┌─────────────────────────────────────────────────────────┐
│ (Coordinator v3: Bounded Loop)                          │
│ - Max 3 interactions per session                         │
│ - Clear stop conditions (stop keyword OR max reached)    │
│ - No memory between turns                               │
└────────────────────┬────────────────────────────────────┘
                     │
     ┌───────────────┴───────────────┐
     │                               │
     ↓                               ↓
┌───────────────────┐      ┌─────────────────────┐
│ 1. InputTrigger   │      │ 5. OutputSink       │
│ (Porcupine)       │      │ (Edge-TTS + LiveKit)│
│ "argo" detection  │      │ Speaks responses    │
└────────┬──────────┘      └──────────┬──────────┘
         │                            │
         ↓                            ↑
    ┌────────────────────┐   ┌─────────────────┐
    │ 2. SpeechToText    │   │ 4. Response     │
    │ (Whisper)          │   │    Generator    │
    │ Audio → Text       │   │ (Qwen via       │
    └─────────┬──────────┘   │  Ollama)        │
              │               │ Intent → Text  │
              ↓               └────────┬────────┘
         ┌────────────────┐           │
         │ 3. IntentParser│◄──────────┘
         │ (Rule-based)   │
         │ Text → Intent  │
         └────────────────┘
```

## Layer Responsibilities

### Layer 1: InputTrigger (Porcupine Wake Word Detection)

**File:** `core/input_trigger.py`

**Responsibility:**
- Detect wake word "argo" from microphone input
- Invoke callback when wake word detected
- Handle audio capture lifecycle

**What it does:**
- ✅ Listens to microphone continuously
- ✅ Detects Porcupine keyword
- ✅ Triggers callback (non-blocking)
- ✅ Cleans up audio resources

**What it does NOT do:**
- ❌ Process audio beyond wake word detection
- ❌ Transcribe speech
- ❌ Parse intent
- ❌ Generate responses
- ❌ Manage the loop (Coordinator does that)
- ❌ Store configuration (except access key)

**Why Porcupine?**
- Local, deterministic, offline
- No network dependency
- Proven in production systems
- Access key provides security/accountability

---

### Layer 2: SpeechToText (Whisper Transcription)

**File:** `core/speech_to_text.py`

**Responsibility:**
- Convert audio bytes to text
- Use base Whisper model for balanced speed/accuracy

**What it does:**
- ✅ Accept audio bytes + sample rate
- ✅ Run Whisper transcription
- ✅ Return plain text string
- ✅ Exit cleanly on success or error

**What it does NOT do:**
- ❌ Detect wake words
- ❌ Classify intent/meaning
- ❌ Parse structured data from text
- ❌ Generate responses
- ❌ Handle microphone setup (caller does that)
- ❌ Retry on failure
- ❌ Stream transcription (single call = one complete result)

**Why Whisper?**
- Open-source, local
- Base model is fast enough for 3-second recordings
- No cloud dependency
- Consistent quality

---

### Layer 3: IntentParser (Rule-Based Classification)

**File:** `core/intent_parser.py`

**Responsibility:**
- Classify user input into 4 categories
- Deterministic, rule-based (no ML)

**Intent Types:**
- `GREETING` (confidence ≥ 0.95): "hello", "hi", "greetings"
- `QUESTION` (confidence ≥ 0.85): Text contains "?", "what", "why", "how"
- `COMMAND` (confidence ≥ 0.75): Imperative verbs like "open", "close", "turn on/off"
- `UNKNOWN` (confidence ≥ 0.10): Everything else

**What it does:**
- ✅ Accept text string
- ✅ Match against patterns
- ✅ Return Intent object (type + confidence)
- ✅ Exit cleanly

**What it does NOT do:**
- ❌ Use ML/NLP models
- ❌ Generate responses
- ❌ Execute commands
- ❌ Maintain state
- ❌ Learn from data
- ❌ Understand context (stateless)

**Why Rule-Based?**
- Deterministic: same input → same output
- Debuggable: easy to trace why classification happened
- No external dependencies
- Explicit, intentional logic
- Fast and predictable

---

### Layer 4: ResponseGenerator (LLM Response Generation)

**File:** `core/response_generator.py`

**Responsibility:**
- Generate response text from Intent via LLM
- **ONLY place where Qwen LLM is called**

**What it does:**
- ✅ Accept Intent object + original user text
- ✅ Build appropriate prompt
- ✅ Call Qwen via Ollama (localhost:11434)
- ✅ Return response string
- ✅ Exit cleanly

**What it does NOT do:**
- ❌ Access audio
- ❌ Detect wake words
- ❌ Parse intent (caller does that)
- ❌ Speak responses (OutputSink does that)
- ❌ Execute commands
- ❌ Maintain conversation memory
- ❌ Store conversations
- ❌ Retry on failure
- ❌ Stream output (single response only)
- ❌ Use tools/functions
- ❌ Tune personality

**Configuration (Hardcoded):**
```python
temperature = 0.7          # Moderate creativity
max_tokens = 100          # Bounded responses
ollama_endpoint = "http://localhost:11434"
model = "argo:latest"     # Qwen via Ollama
```

**Why Isolated?**
- All LLM logic in one file
- Easy to swap LLMs (just change this file)
- Single responsibility: Intent → Text
- Coordinator doesn't know about LLM
- No implicit dependencies

**Why Qwen?**
- Local, open-source
- Reasonable quality + speed tradeoff
- Small enough to run on consumer hardware via Ollama
- No cloud dependency

---

### Layer 5: OutputSink (Edge-TTS + LiveKit)

**File:** `core/output_sink.py`

**Responsibility:**
- Synthesize text to speech (Edge-TTS)
- Publish audio via LiveKit (RTC transport)
- Handle audio lifecycle and delivery

**What it does:**
- ✅ Accept text string
- ✅ Call Edge-TTS to generate audio bytes
- ✅ Create LiveKit JWT token
- ✅ Publish audio to LiveKit room
- ✅ Handle cleanup
- ✅ Exit cleanly

**What it does NOT do:**
- ❌ Generate response text
- ❌ Detect wake words
- ❌ Transcribe audio
- ❌ Parse intent
- ❌ Manage loop
- ❌ Maintain state
- ❌ Handle microphone input
- ❌ Retry on failure

**Why Edge-TTS + LiveKit?**
- Edge-TTS: Microsoft TTS API, consistent quality, local synthesis
- LiveKit: Real RTC protocol (not ad-hoc audio piping), handles packet loss, jitter, timing
- Separation of concerns: speech synthesis (Edge-TTS) vs. audio transport (LiveKit)

---

### Layer 6: Coordinator v3 (Bounded Interaction Loop)

**File:** `core/coordinator.py`

**Responsibility:**
- Orchestrate the 7-layer pipeline
- Enforce loop bounds (max 3 interactions)
- Manage state transitions
- Handle stop conditions

**Loop Behavior:**
```
Iteration 1/3:
  - Wait for wake word → Audio capture → STT → Intent → Response → TTS → Publish
  - If response contains stop keyword → Exit
  - Otherwise, continue to iteration 2

Iteration 2/3:
  - (Same as iteration 1)

Iteration 3/3:
  - (Same as iteration 1)
  - Max reached → Exit

Clean exit with summary
```

**What it does:**
- ✅ Wire InputTrigger → SpeechToText → IntentParser → ResponseGenerator → OutputSink
- ✅ Enforce max 3 interactions
- ✅ Check for stop keywords in response
- ✅ Log each iteration
- ✅ Clean exit

**What it does NOT do:**
- ❌ Detect wake words (InputTrigger does that)
- ❌ Transcribe audio (SpeechToText does that)
- ❌ Classify intent (IntentParser does that)
- ❌ Generate responses (ResponseGenerator does that)
- ❌ Speak responses (OutputSink does that)
- ❌ Maintain conversation memory
- ❌ Make decisions beyond "continue or exit"
- ❌ Retry failed operations

**Why Bounded?**
- Prevents runaway loops
- Clear, predictable behavior
- Easy to debug
- No surprise behavior

**Why No Memory?**
- Each turn is independent
- No context contamination
- Stateless: easier to reason about
- Safer: no implicit assumptions

---

### Layer 7: Run Script (Initialization & Cleanup)

**File:** `run_coordinator_v3.py`

**Responsibility:**
- Import all layers
- Initialize Coordinator v3
- Run the bounded loop
- Clean up and exit

## Design Decisions

### Why 7 Layers?

Each layer handles exactly one concern:

1. **InputTrigger** — Wake word (deterministic)
2. **SpeechToText** — Transcription (deterministic)
3. **IntentParser** — Classification (deterministic)
4. **ResponseGenerator** — Generation (intelligent, one LLM call)
5. **OutputSink** — Output (deterministic)
6. **Coordinator** — Orchestration (deterministic)
7. **Run Script** — Initialization (deterministic)

Clear separation makes debugging easy. Each layer can be tested independently.

### Why Rule-Based Intent Parser?

**Rejected alternatives:**
- ML model: Added unpredictability, hard to debug
- Large language model: Overkill for 4 categories, added latency
- Hand-written regex: Fragile, hard to extend

**Chosen: Rule-based classification**
- Explicit, intentional logic
- Deterministic: same input → same output
- Debuggable: easy to trace why classification happened
- Extensible: add rules without retraining

### Why LLM Only in Layer 4?

**Rejected: LLM everywhere**
- InputTrigger using LLM: Unreliable wake word detection
- SpeechToText using LLM: Overkill for transcription
- IntentParser using LLM: Adds unpredictability
- OutputSink using LLM: Unnecessary

**Chosen: LLM isolated in ResponseGenerator**
- All intelligence in one place
- Clear contract: Intent → Response
- Easy to replace LLM without touching other layers
- Simplifies testing and debugging

### Why LiveKit Over Ad-Hoc Audio?

**Rejected: Raw socket audio piping**
- Latency unpredictable
- Packet loss not handled
- Jitter causes audio artifacts
- Lifecycle unclear

**Chosen: LiveKit RTC transport**
- Proven protocol for real-time audio
- Handles packet loss, jitter, timing
- Real transport, not ad-hoc piping
- Local server available, no cloud required

## What We Tried and Rejected

### 1. Single Monolithic Loop

```python
# Rejected pattern
while True:
    audio = capture_audio()
    text = transcribe(audio)
    response = generate_with_llm(text)
    speak(response)
    # But what about intent? What about boundaries?
```

**Problems:**
- No clear responsibilities
- Hard to debug
- No intent classification
- Loop never exits (no bounds)
- Everything tangled together

**Solution: 7-layer pipeline with Coordinator v3**

---

### 2. Implicit Memory (Context Carryover)

```python
# Rejected pattern
context = []
while count < 3:
    response = generate_with_llm(query, context=context)  # Implicit carryover
    context.append(response)  # Contaminate future turns
```

**Problems:**
- Context becomes incoherent
- Hard to reason about state
- Violates statelessness principle
- Future interactions depend on past garbage

**Solution: Each turn completely independent, no memory**

---

### 3. Wake Word Detection in Pure Python

```python
# Rejected pattern
def detect_wake_word(audio):
    # Implement Porcupine ourselves?
    # Hand-written pattern matching?
    # Try to detect "argo" with regex?
```

**Problems:**
- Unreliable, missed detections
- Hard to get right
- No production track record
- Reinventing the wheel

**Solution: Use proven Porcupine library**

---

### 4. Ad-Hoc Audio Piping

```python
# Rejected pattern
audio_data = b""
while True:
    chunk = microphone.read()
    audio_data += chunk
    if len(audio_data) > 48000:
        # Hope it's valid audio?
        break
```

**Problems:**
- Timing unpredictable
- Packet loss not handled
- No real transport protocol
- Lifecycle unclear
- Audio artifacts due to jitter

**Solution: Use LiveKit (real RTC protocol)**

---

### 5. Overloaded Coordinator

```python
# Rejected pattern
class Coordinator:
    def run(self):
        # Handle audio capture
        # Handle intent classification
        # Handle LLM calls
        # Handle TTS
        # Handle loop bounds
        # 1000+ lines of spaghetti
```

**Problems:**
- Hard to debug
- Tight coupling
- Violates single responsibility
- Hard to test
- Hard to replace components

**Solution: Each layer isolated, Coordinator only orchestrates**

---

### 6. Stateful Voice Mode

```python
# Rejected pattern
def voice_mode():
    memory = []
    while True:
        query = transcribe()
        # Inject memory into prompt
        response = generate_with_llm(query, memory=memory)
        memory.append(response)
        speak(response)
```

**Problems:**
- Memory becomes garbage
- Context contamination
- Hard to debug
- No way to reset context
- Violates design principle of statelessness

**Solution: Stateless voice mode, each turn fresh**

---

### 7. No Intent Classification

```python
# Rejected pattern
def generate_response(query):
    # Just send to LLM directly
    return ollama(query)
    # But what if it's a greeting? Command? Question?
    # LLM will generate bloated responses
```

**Problems:**
- LLM generates generic responses
- No customization per intent type
- Responses are longer than necessary
- No safety layer (all queries treated equally)

**Solution: Explicit intent classification before LLM**

---

## Testing Strategy

### Layer Testing

Each layer has independent unit tests:
- InputTrigger: Mock Porcupine, test callback
- SpeechToText: Test with sample audio, verify transcription
- IntentParser: Test patterns, verify classifications
- ResponseGenerator: Mock LLM, test prompt building
- OutputSink: Mock Edge-TTS, verify LiveKit publishing
- Coordinator: Simulated tests, verify loop bounds and stop conditions

### Integration Testing

`test_coordinator_v3_simulated.py`:
- 3 simulated end-to-end tests
- Test 1: Verify max 3 interactions enforced
- Test 2: Verify stop keyword exits early
- Test 3: Verify independent turns (no context carryover)

### All 3 Tests Passing ✅

```
test_coordinator_v3_simulated.py::test_loop_max_interactions PASSED
test_coordinator_v3_simulated.py::test_stop_keyword_exits_early PASSED
test_coordinator_v3_simulated.py::test_independent_turns PASSED
```

## Performance Characteristics

| Component | Typical Latency | Notes |
|-----------|-----------------|-------|
| Wake word detection | Continuous | Always listening |
| Audio capture | 3 seconds | Hardcoded duration |
| Whisper STT | 1-2 seconds | Base model, local |
| Intent classification | < 50ms | Rule-based, no ML |
| Qwen LLM inference | 2-5 seconds | Depends on hardware |
| Edge-TTS synthesis | < 1 second | Typically fast |
| LiveKit publish | < 100ms | Network dependent |
| **Total per turn** | **8-12 seconds** | Typical end-to-end |

## Future Evolution

See [MILESTONES.md](MILESTONES.md) for planned enhancements:

- **Milestone 2: Session Memory** — Optional explicit context (opt-in)
- **Milestone 3: Multi-Room / Multi-Device** — Multiple Coordinators
- **Milestone 4: Personality Layer** — Custom voice personas

Each milestone maintains the 7-layer architecture and design principles.

## Conclusion

ARGO's architecture prioritizes **clarity and predictability over features**.

Every layer has a single responsibility.
Every decision is intentional and documented.
Every behavior is bounded and debuggable.

This is not accidental. This was designed.
