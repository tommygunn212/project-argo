# Coordinator v2: LLM Response Integration

**TASK 12 — Upgrade Coordinator to use ResponseGenerator (LLM) instead of hardcoded responses**

## Overview

Coordinator v2 replaces hardcoded response dict with LLM-powered responses via ResponseGenerator, using pure dependency injection. No logic changes, no flow changes—just swapping where responses come from.

### Key Principle

> **Coordinator is dumb. It doesn't know or care that responses come from an LLM. It just calls `generator.generate(intent)`.**

When the LLM breaks, fix it in ResponseGenerator. Coordinator stays the same.

---

## What Changed (v1 → v2)

### 1. Removed Hardcoded RESPONSES Dict

**Before (v1)**:
```python
RESPONSES = {
    "greeting": "Hello! How can I help you?",
    "question": "I don't have access to that information.",
    "command": "I'll do that for you.",
    "unknown": "I'm sorry, I didn't understand that.",
}
```

**After (v2)**:
Removed completely. Response generation delegated to ResponseGenerator.

### 2. Updated Constructor

**Before (v1)**:
```python
def __init__(self, input_trigger, speech_to_text, intent_parser, output_sink):
    self.trigger = input_trigger
    self.stt = speech_to_text
    self.parser = intent_parser
    self.sink = output_sink
```

**After (v2)**:
```python
def __init__(self, input_trigger, speech_to_text, intent_parser,
             response_generator, output_sink):
    self.trigger = input_trigger
    self.stt = speech_to_text
    self.parser = intent_parser
    self.generator = response_generator  # ← NEW
    self.sink = output_sink
```

### 3. Updated Response Selection

**Before (v1)** (Step 4):
```python
response_text = RESPONSES.get(intent.intent_type.value, RESPONSES["unknown"])
```

**After (v2)** (Step 4):
```python
response_text = self.generator.generate(intent)
```

---

## What Did NOT Change

✅ **Pipeline Flow**: Same 7-step flow  
✅ **All Layers**: InputTrigger, SpeechToText, IntentParser, OutputSink unchanged  
✅ **Interface**: Constructor signature looks the same (just one more param)  
✅ **Logic**: Coordinator is still pure orchestration (dumb wiring)  
✅ **Error Handling**: Same try/except, same logging  

---

## Full Pipeline (v2)

```
┌─ WAKE WORD ────────────────────────────────────────────────────────┐
│  1. InputTrigger.on_trigger() fires (Porcupine detected "computer")  │
└────────────────────────────────────────────────────────────────────┘
                            ↓
┌─ AUDIO CAPTURE ────────────────────────────────────────────────────┐
│  2. Record 5 seconds of user speech (via sounddevice)              │
└────────────────────────────────────────────────────────────────────┘
                            ↓
┌─ SPEECH-TO-TEXT ───────────────────────────────────────────────────┐
│  3. SpeechToText.transcribe(audio) → "what's the weather"          │
└────────────────────────────────────────────────────────────────────┘
                            ↓
┌─ INTENT CLASSIFICATION ────────────────────────────────────────────┐
│  4. IntentParser.parse(text) → Intent(type=QUESTION, confidence=0.95) │
└────────────────────────────────────────────────────────────────────┘
                            ↓
┌─ RESPONSE GENERATION (LLM) ────────────────────────────────────────┐
│  5. ResponseGenerator.generate(intent) → "I don't have access to..." │
│     (Calls Qwen via Ollama, respects intent context)               │
└────────────────────────────────────────────────────────────────────┘
                            ↓
┌─ AUDIO OUTPUT ────────────────────────────────────────────────────┐
│  6. OutputSink.speak(response) → publish via LiveKit               │
│     (Edge-TTS transcodes to audio first)                           │
└────────────────────────────────────────────────────────────────────┘
                            ↓
┌─ EXIT ────────────────────────────────────────────────────────────┐
│  7. Exit cleanly                                                    │
└────────────────────────────────────────────────────────────────────┘
```

**Key Difference from v1**: Step 5 now calls LLM instead of dict lookup.

---

## Usage

### Initialization

```python
from core.input_trigger import PorcupineWakeWordTrigger
from core.speech_to_text import WhisperSTT
from core.intent_parser import RuleBasedIntentParser
from core.response_generator import LLMResponseGenerator  # ← NEW
from core.output_sink import EdgeTTSLiveKitOutputSink
from core.coordinator import Coordinator

# Initialize all layers
trigger = PorcupineWakeWordTrigger()
stt = WhisperSTT()
parser = RuleBasedIntentParser()
generator = LLMResponseGenerator()  # ← NEW
sink = EdgeTTSLiveKitOutputSink()

# Wire into Coordinator v2
coordinator = Coordinator(
    input_trigger=trigger,
    speech_to_text=stt,
    intent_parser=parser,
    response_generator=generator,  # ← NEW parameter
    output_sink=sink,
)

# Run end-to-end
coordinator.run()
```

### Example Output

```
[Coordinator] Starting Coordinator v2 (LLM-based responses)...
[Coordinator] Initializing ResponseGenerator
[Coordinator] [Step 1] Waiting for wake word...
[Coordinator] Wake word detected!
[Coordinator] [Step 2] Recording audio for 5 seconds...
[Coordinator] [Step 3] Transcribing audio...
[Coordinator] User said: "what's the weather?"
[Coordinator] [Step 4] Parsing intent...
[Coordinator] Intent: question (confidence: 0.95)
[Coordinator] [Step 5] Generating response (via LLM)...
[Coordinator] Response: "I'm sorry, I don't have access to current weather information..."
[Coordinator] [Step 6] Speaking response...
[Coordinator] Response spoken
[Coordinator] [Step 7] Exiting...
[Coordinator] Pipeline complete
```

---

## Comparison: v1 vs v2

| Aspect | v1 | v2 |
|--------|----|----|
| **Response Source** | Dict lookup | LLM (Qwen) |
| **Response Quality** | Generic, same every time | Dynamic, context-aware |
| **Constructor Param Count** | 4 layers | 5 layers |
| **ResponseGenerator Required** | No | Yes |
| **Pipeline Flow** | Same | Same |
| **Intent Parsing** | Same (rules) | Same (rules) |
| **LLM Isolation** | N/A | Fully isolated in ResponseGenerator |
| **Code Changed** | — | 3 replacements in coordinator.py |
| **Other Layers Changed** | — | 0 changes |

---

## Testing

### Test Files

1. **test_coordinator_v2_simulated.py**
   - Simulated test with mocked trigger/STT
   - REAL ResponseGenerator (tests LLM integration)
   - Tests 7 different intents
   - Verifies intent parsing + LLM response generation

### Running Tests

```bash
# Simulated test (no hardware required)
python test_coordinator_v2_simulated.py

# Expected output:
# [Test 1] greeting/hello
#   Input text: 'hello there'
#   Intent: greeting (confidence: 0.95)
#   ✓ Matches expected: greeting
#   Response: 'Hello! How can I assist you today?'
#   ✓ LLM generated response
#   ...
# TEST SUMMARY
# Intent Classification: 7/7 correct
# LLM Response Generation: 7/7 generated
# ✓ SUCCESS: All 7 tests passed!
```

### Full Pipeline Test

```bash
# Real end-to-end with actual hardware
python run_coordinator_v2.py

# Requires:
# - Working microphone
# - Porcupine key in LICENSE file
# - Ollama server running (localhost:11434)
# - LiveKit server running
```

---

## Architecture: Why LLM is Isolated

### Problem (Pre-v2)

In v1, responses are hardcoded by intent type. Not flexible.

### Solution (v2)

LLM lives entirely in ResponseGenerator:

```
Coordinator v2          ResponseGenerator
├─ on_trigger()         ├─ generate(intent)
├─ record()             │  ├─ Ollama HTTP call
├─ transcribe()         │  ├─ Temperature: 0.7
├─ parse()              │  ├─ Max tokens: 100
├─ GENERATE (calls)     │  ├─ Prompt templates (4 types)
│  └─ generator.        │  └─ Return text
│     generate(intent)  │
├─ speak()              (All LLM code here)
└─ exit()
```

### Benefits

✅ **Single Source of Truth**: All LLM logic in one file  
✅ **Easy to Debug**: LLM broken? Fix ResponseGenerator  
✅ **Easy to Replace**: Swap ResponseGenerator implementation (e.g., use cloud API)  
✅ **No Coupling**: Other layers don't know about LLM  
✅ **Easy to Test**: Mock ResponseGenerator for unit tests  

---

## Migration Path: v1 → v2

For users running v1:

```python
# Old way (v1)
coordinator = Coordinator(trigger, stt, parser, sink)
coordinator.run()  # Returns hardcoded responses

# New way (v2)
generator = LLMResponseGenerator()  # ← Add this
coordinator = Coordinator(trigger, stt, parser, generator, sink)  # ← Pass generator
coordinator.run()  # Returns LLM responses
```

**No other code changes needed.**

---

## Hardcoded LLM Config (v2)

ResponseGenerator hardcodes:

| Setting | Value | Rationale |
|---------|-------|-----------|
| **Model** | argo:latest (Qwen) | 783ms baseline, optimized |
| **Endpoint** | http://localhost:11434 | Local Ollama |
| **Temperature** | 0.7 | Balanced creativity/determinism |
| **Max Tokens** | 100 | Keep responses concise, sub-500ms |
| **Streaming** | Off | Simpler implementation, less latency variance |

See `/docs/response_generator.md` for full details.

---

## Error Handling

### If Ollama is Down

ResponseGenerator.generate() will raise an exception. Coordinator catches it in try/except at top level:

```python
try:
    coordinator.run()
except Exception as e:
    logger.error(f"Pipeline failed: {e}")
    # Clean up and exit
```

### If Response is Empty

ResponseGenerator should never return empty string (raises exception first). Coordinator assumes response_text is always non-empty.

### If Intent is UNKNOWN

ResponseGenerator still generates a response (template for UNKNOWN type). Coordinator treats UNKNOWN same as other intents.

---

## Files in This Task (TASK 12)

| File | Purpose | Status |
|------|---------|--------|
| **core/coordinator.py** | Updated to accept ResponseGenerator | ✅ MODIFIED (v2 logic) |
| **run_coordinator_v2.py** | Full-flow example with LLM | ✅ NEW |
| **test_coordinator_v2_simulated.py** | Simulated test with LLM | ✅ NEW |
| **docs/coordinator_v2.md** | This documentation | ✅ NEW |

---

## Validation Checklist

- [x] Coordinator accepts ResponseGenerator parameter
- [x] Hardcoded RESPONSES dict removed
- [x] Response generation delegates to generator.generate(intent)
- [x] All other layers unchanged (InputTrigger, SpeechToText, IntentParser, OutputSink)
- [x] Pipeline flow unchanged (same 7 steps)
- [x] run_coordinator_v2.py demonstrates full LLM flow
- [x] test_coordinator_v2_simulated.py tests LLM integration
- [x] Documentation explains v1 → v2 changes
- [x] No regressions to v1 tests

---

## Next Steps (After TASK 12)

Once v2 is validated:

1. Memory/conversation history (multi-turn dialog)
2. Error recovery and retries
3. Production hardening
4. Remote access (iPad)

---

## See Also

- [/docs/STACK_CONTRACT.md](/docs/STACK_CONTRACT.md) — Architecture locked
- [/docs/response_generator.md](/docs/response_generator.md) — LLM isolation details
- [/docs/coordinator_v1.md](/docs/coordinator_v1.md) — v1 documentation
- [/core/coordinator.py](/core/coordinator.py) — Implementation
- [/core/response_generator.py](/core/response_generator.py) — LLM layer
