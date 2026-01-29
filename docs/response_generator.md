# Response Generator (LLM, Isolated)

## Objective

Isolated boundary layer that converts Intent → Response string via LLM.

**Single responsibility**: Given an intent classification and user input, generate an appropriate response

Nothing more.

---

## What ResponseGenerator Does

| Action | Status |
|--------|--------|
| Accept Intent object | ✅ YES |
| Build context-aware prompt | ✅ YES |
| Call local LLM (Qwen) | ✅ YES |
| Generate response text | ✅ YES |
| Return plain string | ✅ YES |
| Exit cleanly | ✅ YES |

---

## What ResponseGenerator Does NOT Do

| Behavior | Status | Why |
|----------|--------|-----|
| Access audio | ❌ NO | That's SpeechToText |
| Detect wake words | ❌ NO | That's InputTrigger |
| Control flow | ❌ NO | That's Coordinator |
| Call OutputSink | ❌ NO | Caller does that |
| Call SpeechToText | ❌ NO | Caller does that |
| Maintain memory | ❌ NO | Stateless (no history) |
| Store conversations | ❌ NO | No persistence |
| Retry on failure | ❌ NO | Single attempt only |
| Stream output | ❌ NO | Single response only |
| Use tools/functions | ❌ NO | Plain generation only |
| Tune personality | ❌ NO | Hardcoded prompts only |
| Access external APIs | ❌ NO | Local LLM only |
| Rate-limit handling | ❌ NO | Single-shot semantics |

---

## Deterministic Bypasses (No LLM)

The generator returns immediate, deterministic responses for:
- System health queries (CPU/RAM/GPU/OS/motherboard)
- Disk usage queries (per-drive, fullest, most free)

These never call the LLM.

---

## Implementation: LLMResponseGenerator

### Model Configuration

```python
# Hardcoded for predictability
Model: qwen:latest (Qwen via Ollama, local endpoint)
Temperature: 0.7 (deterministic but creative)
Max tokens: 100 (keep responses brief)
Streaming: False (single response, not streaming)
```

### LLM Endpoint

```python
# Local Ollama server (must be running)
Base URL: http://localhost:11434
Endpoint: /api/generate
Timeout: 30 seconds
```

### Input: Intent Object

```python
@dataclass
class Intent:
    intent_type: IntentType  # GREETING, QUESTION, COMMAND, UNKNOWN
    confidence: float        # 0.0 (low) to 1.0 (high)
    raw_text: str           # Original user input
```

### Prompt Engineering (By Intent Type)

#### GREETING
```
The user greeted you with: '{raw_text}'
Respond with a friendly, brief greeting (one sentence max).
Response:
```

#### QUESTION
```
The user asked: '{raw_text}'
Provide a helpful, brief answer (one or two sentences max).
Response:
```

#### COMMAND
```
The user gave a command: '{raw_text}'
Acknowledge the command with a brief confirmation (one sentence max).
Response:
```

#### UNKNOWN
```
The user said: '{raw_text}'
You didn't understand. Politely ask for clarification (one sentence max).
Response:
```

### Output: Response String

- Plain text (no markdown, no formatting)
- Single response (no alternatives)
- Brief (max ~100 tokens)
- Conversational (natural language)

---

## Interface

```python
class ResponseGenerator(ABC):
    def generate(self, intent: Intent) -> str:
        """Convert Intent to response string."""
        pass
```

### Input Format

- **Intent**: Intent dataclass with type, confidence, raw_text
- **Responsibility**: Caller ensures Intent is valid

### Output Format

- **Text**: Single string response
- **Encoding**: UTF-8
- **No Metadata**: Just plain text
- **Single Attempt**: One generate() call = one response

---

## Usage

### Basic Example

```python
from core.intent_parser import IntentType, Intent
from core.response_generator import LLMResponseGenerator

# Initialize generator (connects to Ollama)
generator = LLMResponseGenerator()

# Create an intent
intent = Intent(
    intent_type=IntentType.QUESTION,
    confidence=1.0,
    raw_text="what time is it?"
)

# Generate response
response = generator.generate(intent)
print(response)
# Output: "I don't have access to the current time, but you can check your device."
```

### Test Script

```bash
python test_response_generator_example.py
```

Creates 4 fake Intent objects → generates responses → prints results → exits.

**Example Output**:
```
[Test 1] Intent: greeting
       Text: 'hello there'
       [OK] Response: 'Hello! How can I assist you today?'

[Test 2] Intent: question
       Text: 'what's the weather today?'
    [OK] Response: 'I don’t have access to live weather data.'

[Test 3] Intent: command
       Text: 'play some music'
       [OK] Response: '"Sure, I'll play some music for you."'

[Test 4] Intent: unknown
       Text: 'xyzabc foobar'
    [OK] Response: 'Can you clarify that?'
```

---

## Why This Is Isolated

### Separation of Concerns

```
SpeechToText (TASK 8)       ← "What did they say?"
    ↓
IntentParser (TASK 9)       ← "What does that mean?"
    ↓
ResponseGenerator (TASK 11) ← "What should we say?" (NEW)
    ↓
OutputSink (TASK 5)         ← "How do we say it?"
```

Each layer has one job:
- SpeechToText: Audio → text
- IntentParser: Text → intent
- **ResponseGenerator: Intent → response**
- OutputSink: Response → audio

### Why LLMs Live Here (And Only Here)

**Current Architecture**:
- InputTrigger: Lightweight (no LLM)
- SpeechToText: Heavyweight (Whisper), but deterministic (no LLM)
- IntentParser: Lightweight (rules), no LLM
- **ResponseGenerator: HERE (LLM, heavyweight, generative)**
- OutputSink: Lightweight (TTS)

**Why This Design**:

1. **Containment**: LLM intelligence is isolated in one box
2. **Debuggability**: If LLM misbehaves, you know exactly where
3. **Replaceability**: Can swap LLM without touching other layers
4. **Testability**: Can mock ResponseGenerator for testing Coordinator
5. **Cost**: LLM only runs when generating responses, not for classification/detection

### When LLM Misbehaves

If the LLM generates inappropriate responses:

**Before** (if LLM was scattered everywhere):
- Search whole codebase for LLM calls
- Understand how each layer uses it
- Complex refactoring needed

**After** (TASK 11):
- Go to `/core/response_generator.py`
- Fix the prompt engineering in `_build_prompt()`
- Done

That's real engineering.

---

## Hardcoded Choices

| Choice | Value | Rationale |
|--------|-------|-----------|
| LLM | Qwen (qwen:latest) | Local, 783ms baseline |
| Transport | Ollama HTTP | Standard local LLM interface |
| Temperature | 0.7 | Balanced (deterministic but creative) |
| Max tokens | 100 | Keep responses brief |
| Streaming | False | Single response, no buffering |
| Endpoint | localhost:11434 | Local dev environment |
| Timeout | 30 seconds | Reasonable for CPU inference |
| Retry logic | None | Single attempt (caller decides) |
| Memory | None | Stateless (new session each call) |

---

## Constraints Respected

✅ **LLM lives here only**: All LLM calls isolated in ResponseGenerator

✅ **No memory**: Stateless (same intent always produces similar responses)

✅ **No retries**: Single attempt (exception bubbles up)

✅ **Single-shot**: One generate() call = one response

✅ **No streaming**: Waiting for complete response

✅ **No tool calling**: Plain text generation only

✅ **No personality tuning**: Hardcoded prompts only

✅ **No side effects**: Pure function (intent in, text out)

✅ **No external dependencies**: Local LLM only

---

## Error Handling

### Expected Errors

| Error | Cause | Behavior |
|-------|-------|----------|
| ImportError | requests not installed | Raise at init |
| ValueError | intent is None | Raise immediately |
| RuntimeError | Ollama not running | Raise with clear message |
| RuntimeError | LLM returns empty | Raise with details |
| RequestsError | Network timeout | Raise (30s timeout) |

### No Retries

- Single attempt only
- Exceptions bubble up
- Caller decides if retry is needed

### Example Error

```
RuntimeError: Failed to connect to Ollama at http://localhost:11434.
Make sure Ollama is running.
```

---

## Testing

### Test Script (test_response_generator_example.py)

```
1. Initialize LLMResponseGenerator (connects to Ollama)
2. Create 4 fake Intent objects (GREETING, QUESTION, COMMAND, UNKNOWN)
3. Call generate() for each intent
4. Print generated responses
5. Exit cleanly
```

### Test Cases

| Intent Type | Input | Expected Behavior | Status |
|-------------|-------|-------------------|--------|
| GREETING | "hello there" | Friendly greeting | ✅ |
| QUESTION | "what's the weather?" | Helpful answer attempt | ✅ |
| COMMAND | "play some music" | Acknowledgment | ✅ |
| UNKNOWN | "xyzabc foobar" | Request clarification | ✅ |

### Success Criteria

- [x] LLM connection successful
- [x] All 4 intent types generate responses
- [x] Responses are contextually appropriate
- [x] Program exits cleanly (no hanging)

---

## Architecture Position

### Complete 6-Layer Spine (5 Working + LLM)

```
InputTrigger (TASK 6)           ← Wake word detection
    ↓
SpeechToText (TASK 8)           ← Audio to text
    ↓
IntentParser (TASK 9)           ← Text to intent
    ↓
ResponseGenerator (TASK 11)     ← Intent to response (NEW, with LLM)
    ↓
Coordinator v2 (TASK 11+)       ← Orchestration (will use ResponseGenerator)
    ↓
OutputSink (TASK 5)             ← Text to audio
```

---

## How This Plugs Into Coordinator v2

### Current (TASK 10)

```python
# Coordinator v1: Hardcoded responses
RESPONSES = {
    "greeting": "Hello.",
    "question": "I heard a question.",
    ...
}
response_text = RESPONSES[intent.intent_type.value]
```

### Future (Coordinator v2 - TASK 11+)

```python
# Coordinator v2: LLM-based responses
generator = LLMResponseGenerator()
response_text = generator.generate(intent)
```

### No Other Code Changes

```python
# Coordinator v2 code stays almost identical:
coordinator = Coordinator(trigger, stt, parser, sink)
coordinator.run()
```

Only difference: ResponseGenerator handles response selection instead of hardcoded dict.

---

## Why This Matters

### Before (Without Isolation)

If LLM logic was scattered:
- InputTrigger might use LLM for filtering
- IntentParser might use LLM for classification
- OutputSink might use LLM for tone adjustment
- Coordinator might use LLM for routing

**Result**: Debugging nightmare. LLM calls everywhere.

### After (TASK 11)

All LLM logic in one place:
- **Only ResponseGenerator uses LLM**
- Other layers are deterministic
- Easy to test (mock generator)
- Easy to debug (one file)
- Easy to replace (one interface)

---

## Future Enhancements (NOT in scope)

❌ Memory/conversation history (future layer)
❌ Tool calling / function execution (future layer)
❌ Personality tuning (future config)
❌ Multi-turn context (future layer)
❌ Model selection (hardcoded now)
❌ Temperature tuning (hardcoded now)
❌ Token budgeting (hardcoded now)

---

## Summary

| Aspect | Value |
|--------|-------|
| **What** | Intent → Response text generation via LLM |
| **How** | Qwen (local) with context-aware prompts |
| **Input** | Intent object (type + text + confidence) |
| **Output** | Plain text response string |
| **LLM Location** | Ollama local endpoint (http://localhost:11434) |
| **Isolation** | Complete (no other layers use LLM) |
| **Memory** | None (stateless) |
| **Retries** | None (single attempt) |
| **Streaming** | None (single response) |
| **Stability** | LOCKED (first LLM integration) |

---

**Status**: ✅ **LLM INTEGRATION COMPLETE**

The system can now:
- Detect wake words (InputTrigger)
- Transcribe speech to text (SpeechToText)
- Classify text into intents (IntentParser)
- **Generate responses via LLM** ← NEW
- (Not yet wired to Coordinator, but ready)

**The LLM is here. In a box. With a label on it.**

When it misbehaves—and it will—you'll know exactly where to look.

That's how you build something that survives contact with reality.

---

## Next Steps

- [ ] Coordinator v2: Replace hardcoded responses with ResponseGenerator
- [ ] Memory layer (context/history)
- [ ] Multi-turn dialog
- [ ] Personality tuning
- [ ] Tool/function calling
- [ ] Production hardening
