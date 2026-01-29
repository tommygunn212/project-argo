# Intent Parser

## Objective

Isolated boundary layer that converts raw text into a structured intent object.

**Single responsibility**: Text → Intent classification

Nothing more.

---

## What IntentParser Does

| Action | Status |
|--------|--------|
| Accept text | ✅ YES |
| Classify text | ✅ YES |
| Return Intent object | ✅ YES |
| Provide confidence score | ✅ YES |
| Preserve original text | ✅ YES |
| Exit cleanly | ✅ YES |

---

## What IntentParser Does NOT Do

| Behavior | Status | Why |
|----------|--------|-----|
| Use LLMs | ❌ NO | That's a future enhancement |
| Use embeddings | ❌ NO | Too complex for this layer |
| Call external services | ❌ NO | Completely local |
| Make decisions | ❌ NO | Only classification |
| Generate responses | ❌ NO | That's ResponseGenerator (future) |
| Trigger actions | ❌ NO | That's Coordinator |
| Handle audio | ❌ NO | That's SpeechToText |
| Maintain memory | ❌ NO | Stateless (no conversation history) |
| Add personality | ❌ NO | Just raw rules |
| Retry on failure | ❌ NO | Single classification attempt |

---

## Implementation: RuleBasedIntentParser

### Intent Types (Enum)

```python
GREETING     # Greetings, pleasantries
QUESTION     # Questions, requests for information
COMMAND      # Commands, imperative actions
MUSIC        # Music playback requests
MUSIC_STOP   # Stop music
MUSIC_NEXT   # Next/skip music
MUSIC_STATUS # What's playing
SYSTEM_HEALTH # Deterministic system health/disk queries
SYSTEM_INFO  # Deterministic hardware identity (cpu/ram/gpu/os)
UNKNOWN      # Unclassified, low confidence
```

### Intent Structure

```python
@dataclass
class Intent:
    intent_type: IntentType  # GREETING, QUESTION, COMMAND, MUSIC, UNKNOWN
    confidence: float        # 0.0 (low) to 1.0 (high)
    raw_text: str           # Original input (for debugging)
```

### Classification Rules (Priority Order)

| Rule | Pattern | Intent | Confidence |
|------|---------|--------|------------|
| 0 | System health / disk / hardware keywords | SYSTEM_HEALTH | 1.00 (certain) |
| 1 | Music STOP keywords | MUSIC_STOP | 1.00 (certain) |
| 2 | Music NEXT keywords | MUSIC_NEXT | 1.00 (certain) |
| 3 | Music STATUS keywords | MUSIC_STATUS | 1.00 (certain) |
| 4 | Music phrases / play verbs | MUSIC | 0.95 (high) |
| 5 | Performance words (count/sing/etc.) | COMMAND | 0.90 (high) |
| 6 | Text ends with `?` | QUESTION | 1.00 (certain) |
| 7 | First word in question words | QUESTION | 0.85 (high) |
| 8 | First word in greeting keywords | GREETING | 0.95 (very high) |
| 9 | First word in command verbs | COMMAND | 0.75 (medium) |
| 10 | (None match) | UNKNOWN | 0.10 (low) |

### Hardcoded Keywords

**Greetings**:
```
hello, hi, hey, greetings, good morning, good afternoon, 
good evening, howdy, what's up
```

**Question Words**:
```
what, how, why, when, where, who, which, is, are, 
can, could, would, should, do, does, did
```

**Command Verbs**:
```
play, stop, start, turn, set, open, close, get, show, 
tell, find, search, call, send, create, make, do, run
```

**Music Phrases**:
```
play, put on, throw on, queue up, i want, give me, let me hear
```

---

## Interface

```python
class IntentParser(ABC):
    def parse(self, text: str) -> Intent:
        """Convert text to structured intent."""
        pass
```

### Input Format

- **Text**: String (from SpeechToText or user input)
- **Encoding**: UTF-8
- **Length**: Any (1 character to paragraphs)
- **Case**: Normalized to lowercase internally

### Output Format

- **Intent Object**: Dataclass with type, confidence, raw_text
- **Confidence**: Float [0.0, 1.0]
- **Text Preserved**: Original text stored unmodified

---

## Usage

### Basic Example

```python
from core.intent_parser import RuleBasedIntentParser

parser = RuleBasedIntentParser()

# Example 1: Question
intent = parser.parse("what time is it?")
# → Intent(QUESTION, confidence=1.0, raw_text="what time is it?")

# Example 2: Music
intent = parser.parse("play some music")
# → Intent(MUSIC, confidence=0.95, raw_text="play some music")

# Example 3: Greeting
intent = parser.parse("hello")
# → Intent(GREETING, confidence=0.95, raw_text="hello")

# Example 4: Unknown
intent = parser.parse("xyz123 foobar")
# → Intent(UNKNOWN, confidence=0.1, raw_text="xyz123 foobar")

print(intent)
# → Intent(question, confidence=1.00, text='what time is it?')
```

### Test Script

```bash
python test_intent_parser_example.py
```

Classifies 12 hardcoded text samples → prints Intent objects → exits.

**Example Output**:
```
Text: 'hello'
  -> GREETING (confidence: 0.95)

Text: 'what's the weather?'
  -> QUESTION (confidence: 1.00)

Text: 'play some music'
    -> MUSIC (confidence: 0.95)

Text: 'this is just random text'
  -> UNKNOWN (confidence: 0.10)
```

---

## Isolation: Why It's Separate

### Separation of Concerns

```
SpeechToText (TASK 8)     ← Audio to text (what did they say?)
    ↓
IntentParser (TASK 9)     ← Text to intent (what do they mean?)
    ↓
ResponseGenerator         ← Intent to text (what do we say?)
    ↓
OutputSink (TASK 5)       ← Text to audio (how do we say it?)
```

Each layer has one job:
- SpeechToText: "Convert audio to text"
- **IntentParser: "Classify text into types"**
- ResponseGenerator: "Generate response for intent"
- OutputSink: "Convert text to audio"

### Design Philosophy

**Why not put this inside SpeechToText?**

- SpeechToText only transcribes (audio → text)
- IntentParser only classifies (text → intent)
- Different responsibilities, different tests, different replacements
- SpeechToText could be swapped to faster-whisper without affecting IntentParser

**Why not use an LLM now?**

- Rule-based parsers are fast and predictable
- LLMs are overkill for simple classification
- Rules can be hardcoded for debugging
- Future: LLMs can replace or augment rules (TASK 10+)

**Why are the rules intentionally dumb?**

- Predictability > cleverness
- Easy to test and debug
- Easy to understand behavior
- Easy to extend without breaking

---

## Future Enhancements (NOT in scope)

❌ LLM-based intent classification (future TASK)
❌ Multi-intent detection (one intent per text)
❌ Named entity extraction (e.g., "movie" from "play Inception")
❌ Semantic similarity scoring (embeddings)
❌ Confidence calibration (fixed thresholds now)
❌ Multi-language support (English only)
❌ Context/memory aware parsing (stateless now)

---

## How LLM-Based Parsers Will Replace This

### Current (TASK 9)

```python
parser = RuleBasedIntentParser()
intent = parser.parse("what's the weather?")
# Rules → QUESTION (1.0)
```

### Future (TASK 10+)

```python
parser = LLMIntentParser()  # Uses Qwen
intent = parser.parse("what's the weather?")
# LLM → QUESTION + {"topic": "weather", "entity": null}
```

### No Code Changes Required

```python
# This code stays the same:
parser: IntentParser  # Could be any subclass
intent = parser.parse(text)
```

The abstraction allows seamless replacement. New parsers inherit from `IntentParser` and implement `parse()`.

---

## Hardcoded Choices

| Choice | Value | Rationale |
|--------|-------|-----------|
| Intent Types | 4 types (GREETING, QUESTION, COMMAND, UNKNOWN) | Simplest useful set |
| Confidence Range | [0.0, 1.0] | Standard scoring |
| Classification | Rule-based, priority-ordered | Predictable, debuggable |
| Language | English only | Hardcoded for simplicity |
| First-Word Matching | Case-insensitive | Robust to capitalization |
| No LLMs | Never | Local, predictable, fast |

---

## Constraints Respected

✅ **No LLM calls**: Rules only, no intelligence layer

✅ **No External Services**: Completely local

✅ **No Memory**: Stateless (same text always produces same intent)

✅ **No Personality**: Raw classification, no tweaks

✅ **No Side Effects**: Pure function (text in, Intent out)

✅ **Single-Shot**: One parse() call = one Intent

✅ **Hardcoded Everything**: No configuration files, no models

---

## Error Handling

### Expected Errors

| Error | Cause | Behavior |
|-------|-------|----------|
| ValueError | Text is empty | Raise ValueError |
| ValueError | Text is None | Raise ValueError |

### No Retries

- Single classification attempt
- No fallback mechanisms
- Caller decides if retry is needed

---

## Testing

### Test Script (test_intent_parser_example.py)

```
1. Initialize RuleBasedIntentParser
2. Classify 12 hardcoded text samples
3. Print each Intent object
4. Exit cleanly
```

### Test Cases Covered

| Text | Expected Intent | Confidence |
|------|-----------------|-----------|
| "hello" | GREETING | 0.95 |
| "hi there" | GREETING | 0.95 |
| "what time is it" | QUESTION | 0.85 |
| "what's the weather?" | QUESTION | 1.00 |
| "play some music" | COMMAND | 0.75 |
| "stop that" | COMMAND | 0.75 |
| "this is just random text" | UNKNOWN | 0.10 |
| "good morning" | UNKNOWN | 0.10 (good_morning not in rules) |
| "can you help me" | QUESTION | 0.85 |
| "turn off the lights" | COMMAND | 0.75 |
| "why is the sky blue?" | QUESTION | 1.00 |
| "tell me a joke" | COMMAND | 0.75 |

### Success Criteria

- [x] Parser initializes without error
- [x] All test cases classified correctly
- [x] Confidence scores assigned per rules
- [x] Original text preserved in Intent
- [x] Program exits cleanly (no hanging)

---

## Architecture Position

### Complete Pipeline (5 Layers)

```
InputTrigger (TASK 6)          ← Wake word detection
    ↓
SpeechToText (TASK 8)          ← Audio to text
    ↓
IntentParser (TASK 9)          ← Text to intent (NEW)
    ↓
[Future] ResponseGenerator     ← Intent to text
    ↓
OutputSink (TASK 5)            ← Text to audio
```

### Each Layer Is Independent

- InputTrigger: Doesn't know about text/intent
- SpeechToText: Doesn't know about intent/response
- **IntentParser: Doesn't know about audio/response**
- ResponseGenerator: Doesn't know about audio/intent
- OutputSink: Doesn't know about intent/transcription

---

## Summary

| Aspect | Value |
|--------|-------|
| **What**: Text-to-intent classification boundary |
| **How**: Rule-based hardcoded heuristics |
| **Input**: Text string |
| **Output**: Intent object (type + confidence + raw_text) |
| **Isolation**: Completely standalone |
| **Future**: LLM-based parsers will extend/replace (TASK 10+) |
| **Stability**: LOCKED (single-responsibility abstraction) |

---

**Status**: ✅ **READY FOR INTEGRATION**

The system can now:
- Detect wake words (InputTrigger)
- Transcribe speech to text (SpeechToText)
- **Classify text into intents (IntentParser)** ← NEW

Still no response generation. Still no LLM usage.

But the meaning extraction boundary is proven and waiting.
