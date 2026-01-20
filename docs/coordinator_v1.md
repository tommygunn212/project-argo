# Coordinator v1: End-to-End Orchestration (Scripted)

## Objective

Upgrade Coordinator to orchestrate all pipeline layers into a single end-to-end flow.

**Single responsibility**: Chain all boundary layers in correct order

Nothing more.

---

## The Pipeline (Exact Order)

```
1. Wait for wake word (InputTrigger)
   └─ Blocking until "computer" or similar detected

2. Record audio (During callback)
   └─ 3-5 second window from microphone

3. Transcribe audio (SpeechToText)
   └─ Convert audio bytes to text string

4. Parse intent (IntentParser)
   └─ Classify text into GREETING, QUESTION, COMMAND, or UNKNOWN

5. Select response (Hardcoded lookup)
   └─ Map intent_type to hardcoded string

6. Speak response (OutputSink)
   └─ Generate audio and publish via LiveKit

7. Exit cleanly
   └─ Return from run(), program ends
```

---

## Architecture

### Five-Layer Spine

```
InputTrigger (TASK 6)
    └─ "Did you hear the wake word?"
    └─ Responsibility: Detect wake words only

SpeechToText (TASK 8)
    └─ "What did the user say?"
    └─ Responsibility: Transcribe audio to text

IntentParser (TASK 9)
    └─ "What does that mean?"
    └─ Responsibility: Classify text into intent types

[Coordinator v1] ← NEW orchestration layer
    └─ Wires all layers together
    └─ Responsibility: Single-shot orchestration

OutputSink (TASK 5)
    └─ "How do we respond?"
    └─ Responsibility: Generate and publish audio
```

### Data Flow

```
Wake Word Detected
    ↓
[Callback triggered]
    ↓
Audio Recorded (3-5s)
    ↓
SpeechToText.transcribe(audio_bytes) → text
    ↓
IntentParser.parse(text) → Intent
    ↓
RESPONSES[intent.intent_type] → response_text
    ↓
OutputSink.speak(response_text)
    ↓
[Callback returns]
    ↓
Program exits
```

---

## Hardcoded Responses

**By intent_type only** (no branching, no conditions):

| Intent Type | Hardcoded Response |
|-------------|-------------------|
| GREETING | "Hello." |
| QUESTION | "I heard a question." |
| COMMAND | "I heard a command." |
| UNKNOWN | "I'm not sure what you meant." |

### Examples

```
User says: "hello"
  → IntentParser: GREETING
  → Response: "Hello."

User says: "what time is it?"
  → IntentParser: QUESTION
  → Response: "I heard a question."

User says: "play music"
  → IntentParser: COMMAND
  → Response: "I heard a command."

User says: "xyzabc foobar"
  → IntentParser: UNKNOWN
  → Response: "I'm not sure what you meant."
```

---

## What Coordinator v1 Does

| Action | Status |
|--------|--------|
| Accept all pipeline layers | ✅ YES |
| Wait for wake word | ✅ YES |
| Record audio (3-5s window) | ✅ YES |
| Transcribe using SpeechToText | ✅ YES |
| Parse intent using IntentParser | ✅ YES |
| Route to hardcoded response | ✅ YES |
| Speak response via OutputSink | ✅ YES |
| Exit cleanly | ✅ YES |

---

## What Coordinator v1 Does NOT Do

| Behavior | Status | Why |
|----------|--------|-----|
| Generate dynamic text | ❌ NO | Responses are hardcoded strings only |
| Call LLM | ❌ NO | No intelligence layer |
| Maintain memory | ❌ NO | Stateless, single-shot |
| Retry on failure | ❌ NO | One attempt only |
| Loop or continue listening | ❌ NO | Fires once, then exits |
| Make decisions beyond routing | ❌ NO | Just lookup intent_type |
| Add personality | ❌ NO | Responses are generic |
| Handle multiple intents | ❌ NO | One intent per text |
| Branch on confidence | ❌ NO | Always use selected response |
| Stream audio | ❌ NO | Record first, process after |

---

## Implementation Details

### Audio Recording

```python
AUDIO_DURATION = 3  # seconds
AUDIO_SAMPLE_RATE = 16000  # Hz (standard)
```

When wake word is detected, callback records 3 seconds of audio.

### Intent Classification Flow

```python
# Within callback:
1. audio = sd.rec(...)          # Record during callback
2. text = stt.transcribe(audio) # Audio → text
3. intent = parser.parse(text)  # Text → Intent
4. response = RESPONSES[intent.intent_type.value]  # Intent → response
5. sink.speak(response)         # Response → audio
```

### Response Mapping

```python
RESPONSES = {
    "greeting": "Hello.",
    "question": "I heard a question.",
    "command": "I heard a command.",
    "unknown": "I'm not sure what you meant.",
}

# Safe lookup (defaults to "unknown" if not found)
response_text = RESPONSES.get(
    intent.intent_type.value,
    RESPONSES["unknown"]
)
```

---

## Why Responses Are Hardcoded

### Intentional Constraints

1. **Predictability**: Same intent always produces same response
2. **Debugging**: Easy to trace which response was selected
3. **Testing**: No non-determinism, no randomness
4. **Speed**: O(1) lookup, no generation delay
5. **Stability**: No model weights, no inference errors

### Future: How LLM-Based Responses Will Extend This

**Current (TASK 10)**:
```python
response_text = RESPONSES[intent.intent_type]  # Hardcoded lookup
```

**Future (TASK 11+)**:
```python
response_generator = LLMResponseGenerator()
response_text = response_generator.generate(intent)  # LLM-based
```

### No Code Changes Required

```python
# This code stays the same:
coordinator = Coordinator(trigger, stt, parser, sink)
coordinator.run()

# Only RESPONSES lookup is replaced
```

---

## What Intelligence Is Intentionally Missing

| Intelligence Layer | Status | Future Task |
|-------------------|--------|------------|
| Wake word detection | ✅ DONE | InputTrigger (TASK 6) |
| Speech-to-text | ✅ DONE | SpeechToText (TASK 8) |
| Intent classification (rules) | ✅ DONE | IntentParser (TASK 9) |
| Response generation | ❌ MISSING | ResponseGenerator (TASK 11+) |
| Memory/conversation history | ❌ MISSING | Memory layer (TASK 12+) |
| Context awareness | ❌ MISSING | Context layer (TASK 13+) |
| Error recovery | ❌ MISSING | Error handling layer (TASK 14+) |
| Multi-turn dialog | ❌ MISSING | Dialog manager (TASK 15+) |

---

## Single-Shot Interaction

### Why One Wake → One Response → Exit?

**Design Philosophy**:
- Simplicity: No loops, no state machines
- Predictability: Exact same flow every time
- Testability: Easy to verify start-to-finish
- Stability: No hanging, no partial states
- Debugging: Clear entry/exit points

### What "Single-Shot" Means

```
┌─────────────────────────────────┐
│ START                           │
├─────────────────────────────────┤
│ Wait for wake word              │
│ (blocks here)                   │
├─────────────────────────────────┤
│ Wake word detected              │
├─────────────────────────────────┤
│ Record audio                    │
├─────────────────────────────────┤
│ Transcribe                      │
├─────────────────────────────────┤
│ Parse intent                    │
├─────────────────────────────────┤
│ Speak response                  │
├─────────────────────────────────┤
│ EXIT                            │
└─────────────────────────────────┘

One shot. Done.
```

### Future: Multi-Turn Dialog

**Current (TASK 10)**: One interaction, exit

**Future (TASK 15+)**:
```
Wake → Listen → Respond → Continue listening (loop)
```

But that's a different Coordinator version.

---

## Error Handling

### Current Behavior

- No retries (single attempt)
- No fallback (exception propagates)
- No recovery (user must restart)
- Exceptions are logged and raised

### Example Error Flows

```
Scenario 1: Microphone unavailable
  └─ Audio recording fails
  └─ Exception raised
  └─ Program exits

Scenario 2: Whisper model fails
  └─ SpeechToText.transcribe() raises
  └─ Exception logged
  └─ Program exits

Scenario 3: LiveKit connection fails
  └─ OutputSink.speak() raises
  └─ Exception logged
  └─ Program exits
```

### Future: Error Recovery

**Current**: Fail fast, clear errors

**Future (TASK 14+)**:
- Retry logic
- Fallback responses
- Degraded mode operation
- User-facing error messages

---

## Usage

### Running the Full Pipeline

```bash
python run_coordinator_v1.py
```

**Expected Flow**:
1. Initialization (all 5 layers load)
2. Wait for wake word ("computer" or "hello")
3. Speak any text after wake word triggers
4. System transcribes → classifies → responds
5. Program exits

### Example Session

```
[*] Initializing pipeline layers...
    [*] InputTrigger (Porcupine)...
        [OK] Wake word detector ready
    [*] SpeechToText (Whisper)...
        [OK] Whisper engine ready
    [*] IntentParser (Rules)...
        [OK] Intent classifier ready
    [*] OutputSink (Edge-TTS + LiveKit)...
        [OK] Audio output ready
[OK] All layers initialized

[*] Waiting for wake word...
    Speak 'computer' or 'hello' to trigger

[Callback] Wake word detected!
[Callback] Recording 3s audio...
[Callback] Recorded 48000 samples
[Callback] Transcribing audio...
[Callback] Transcribed: 'what time is it'
[Callback] Parsing intent...
[Callback] Intent: question (confidence=1.00)
[Callback] Response: 'I heard a question.'
[Callback] Speaking response...
[Callback] Response spoken

[OK] SUCCESS
Pipeline complete: wake → listen → respond → exit
```

---

## Testing the Pipeline

### Suggested Test Cases

1. **Greeting**
   - Say: "hello"
   - Expected: Response "Hello." spoken
   - Intent: GREETING

2. **Question**
   - Say: "what time is it?"
   - Expected: Response "I heard a question." spoken
   - Intent: QUESTION

3. **Command**
   - Say: "play music"
   - Expected: Response "I heard a command." spoken
   - Intent: COMMAND

4. **Unknown**
   - Say: "xyz foobar"
   - Expected: Response "I'm not sure what you meant." spoken
   - Intent: UNKNOWN

---

## Architecture Evolution

### v0 (Previous)
```
InputTrigger → OutputSink
(Pure wiring, hardcoded "Yes?")
```

### v1 (Current - TASK 10)
```
InputTrigger → [Audio Capture] → SpeechToText → IntentParser → [Lookup] → OutputSink
(End-to-end scripted, hardcoded responses by intent_type)
```

### v2 (Future - TASK 11+)
```
InputTrigger → [Audio Capture] → SpeechToText → IntentParser → ResponseGenerator (LLM) → OutputSink
(Dynamic response generation using Qwen)
```

### v3 (Future - TASK 12+)
```
InputTrigger → [Audio Capture] → SpeechToText → IntentParser → ResponseGenerator → Memory/Context → OutputSink
(Multi-turn dialog with conversation history)
```

---

## Constraints Respected

✅ **No LLM calls**: Intent classification is rule-based only

✅ **No dynamic generation**: Responses are hardcoded strings

✅ **No memory**: Stateless (same input always produces same output)

✅ **No retries**: Single attempt (caller must retry if needed)

✅ **No loops**: Single-shot (wake → respond → exit)

✅ **No streaming**: Record first, process after

✅ **No personality**: Generic responses only

✅ **No context carryover**: Each interaction is independent

✅ **Single-shot semantics**: One wake word → one response → program exits

---

## Summary

| Aspect | Value |
|--------|-------|
| **What**: End-to-end orchestration of 5 pipeline layers |
| **How**: Hardcoded routing + scripted responses |
| **Input**: Wake word detection trigger |
| **Output**: Spoken response based on intent classification |
| **Intelligence Level**: None (pure orchestration) |
| **Memory**: None (stateless) |
| **Response Generation**: Hardcoded lookup by intent_type |
| **Single-Shot**: Yes (wake → respond → exit) |
| **Stability**: LOCKED (fully functional baseline) |

---

**Status**: ✅ **SYSTEM IS ALIVE**

The system can now:
- Detect wake words (InputTrigger)
- Transcribe speech to text (SpeechToText)
- Classify text into intents (IntentParser)
- **Select and speak hardcoded responses** ← NEW
- **Execute full end-to-end pipeline** ← NEW

The user says something. The system listens, understands (superficially), and responds (mechanically).

Still no real intelligence. Still no LLM. Still no memory.

But all boundaries are wired and working together.

---

## Next Steps (Not in Scope)

- [ ] Response generation via LLM (TASK 11+)
- [ ] Conversation memory (TASK 12+)
- [ ] Context awareness (TASK 13+)
- [ ] Error recovery (TASK 14+)
- [ ] Multi-turn dialog (TASK 15+)
- [ ] Production hardening
- [ ] Performance optimization

The spine is set. Everything else extends around it.
