# Session Memory: Design & Implementation

## Overview

Session Memory is **short-term working memory for a single session only**.

It stores recent interactions (utterances, intents, responses) so the LLM can reference context within a session. When the program exits, memory is completely cleared.

**Key principle**: Bounded, transparent, temporary scratchpad. Not learning. Not embeddings. Not personality.

## v1.8.0 Boundary Note

SessionMemory is still RAM-only. Durable memory now lives behind `core.memory_store`, which can use SQLite or PostgreSQL. The new durable `conversation_turns` table is separate from SessionMemory and is intended for future long-term recall experiments.

---

## What It Is

**SessionMemory** stores:
- Last N user utterances (e.g., 3)
- Last N intents (e.g., 3)
- Last N responses (e.g., 3)

Using a **ring buffer** that automatically evicts the oldest entry when capacity is exceeded.

### Storage Strategy

```
Capacity: 3 interactions

Turn 1: User says "Hello"
    → Stored
    Memory: [Turn1]

Turn 2: User asks "What time?"
    → Stored
    Memory: [Turn1, Turn2]

Turn 3: User asks "Weather?"
    → Stored
    Memory: [Turn1, Turn2, Turn3]  [FULL]

Turn 4: User says "Goodbye"
    → Stored, Turn1 EVICTED (oldest)
    Memory: [Turn2, Turn3, Turn4]  [FULL]

Program exits
    → All memory CLEARED (not persistent)
    Memory: []
```

---

## What It Is NOT

### ❌ NOT Long-Term Memory
- Clears on program exit
- No disk persistence
- No database storage
- No cross-session carryover

### ❌ NOT Learning
- No preference tracking
- No embedding updates
- No model fine-tuning
- No adaptation over time

### ❌ NOT Personality
- No personality traits stored
- No mood tracking
- No relationship building
- No user profiling

### ❌ NOT Full Conversation History
- Only recent N interactions
- Oldest entries automatically evicted
- Not a transcript
- Not searchable or indexable

### ❌ NOT Smart
- No summarization
- No compression
- No deduplication
- No semantic analysis

### ❌ NOT Hidden
- Completely visible in code
- Explicitly logged
- Read-only for LLM (cannot modify)
- Transparent eviction policy

---

## Why Bounded?

**Bounded memory prevents**:

1. **Unbounded Growth**
   - Memory usage stays fixed (O(1) space)
   - Ring buffer never exceeds capacity
   - No memory leaks from old sessions

2. **Context Pollution**
   - Stale interactions automatically evicted
   - LLM never confused by ancient history
   - Fresh contexts dominate

3. **Predictability**
   - System behavior is deterministic
   - No surprise memory exhaustion
   - No degradation over time

4. **Simplicity**
   - No garbage collection needed
   - No summarization algorithm required
   - No embedding index to maintain
   - No search performance issues

5. **Testing**
   - Memory size always predictable
   - Behavior identical across runs
   - No non-deterministic effects
   - Easy to inspect and verify

---

## Architecture

### SessionMemory Class

Located in `core/session_memory.py`.

```python
class SessionMemory:
    """Bounded ring buffer for session interactions."""
    
    def __init__(self, capacity: int = 3):
        """Store last N interactions (default 3)."""
        self.interactions: deque = deque(maxlen=capacity)
    
    def append(
        self,
        user_utterance: str,
        parsed_intent: str,
        generated_response: str
    ) -> None:
        """Add interaction. Oldest auto-evicted if full."""
    
    def get_recent_utterances(self, n: Optional[int] = None) -> List[str]:
        """Get last N utterances (newest first)."""
    
    def get_context_summary(self) -> str:
        """Get human-readable summary for LLM prompt."""
```

### Integration Points

#### 1. Coordinator v4

- **Instantiates** SessionMemory at startup
- **Appends** after each interaction (utterance, intent, response)
- **Passes** to ResponseGenerator (read-only)
- **Clears** on exit (including error cases)

```python
def __init__(self):
    self.memory = SessionMemory(capacity=3)

def run(self):
    while True:
        # ... interaction loop ...
        
        # Append to memory after speaking response
        self.memory.append(
            user_utterance=text,
            parsed_intent=intent.intent_type.value,
            generated_response=response_text
        )
        
        # ... check stop condition ...
    
    # Clear memory on exit
    self.memory.clear()
```

#### 2. ResponseGenerator v4

- **Accepts** optional SessionMemory parameter
- **References** (read-only) in prompt building
- **Never modifies** memory
- **Explicitly logs** memory usage

```python
def generate(self, intent, memory: Optional[SessionMemory] = None) -> str:
    # ... extract intent details ...
    
    # Reference memory (read-only)
    prompt = self._build_prompt(intent_type, raw_text, confidence, memory)
    
    return self._call_llm(prompt)

def _build_prompt(self, ..., memory: Optional[SessionMemory] = None) -> str:
    context = ""
    if memory is not None and not memory.is_empty():
        # Include context summary in prompt
        context_summary = memory.get_context_summary()
        if context_summary:
            context = f"Context:\n{context_summary}\n\n"
    
    return context + base_prompt
```

---

## Data Flow

### Per-Interaction Flow

```
1. User speaks → InputTrigger detects wake word
2. Audio recorded → SpeechToText transcribes
3. Text transcribed → IntentParser classifies
4. Intent classified → ResponseGenerator.generate(intent, memory)
   a. ResponseGenerator reads memory (inspect recent interactions)
   b. Builds prompt with context from memory
   c. Calls Qwen LLM with enhanced prompt
   d. Returns response (never modifies memory)
5. Response generated → OutputSink speaks
6. Response spoken → Coordinator.append_to_memory(utterance, intent, response)
7. Added to memory → Check stop condition or loop
8. Iteration complete → Next turn or exit
```

### Memory State Example

```
=== Turn 1 ===
User: "Hello"
Intent: GREETING
Response: "Hi there!"
Memory after: [Turn1]
Context for next LLM: (empty, first turn)

=== Turn 2 ===
User: "What time is it?"
Intent: QUESTION
Response: "It's 3 PM"
Memory after: [Turn1, Turn2]
Context for next LLM: "Context: Turn 1 you said 'Hello' and I responded 'Hi there!'"

=== Turn 3 ===
User: "That's early for lunch"
Intent: UNKNOWN
Memory before: [Turn1, Turn2, Turn3-partial]
Context for LLM: "Context: Turn 2 you asked 'What time is it?' and I said 'It's 3 PM'. 
                 Turn 1 you said 'Hello' and I responded 'Hi there!'"
Response: "Would you like lunch recommendations?"
Memory after: [Turn1, Turn2, Turn3]  [FULL]

=== Turn 4 ===
User: "Goodbye"
Intent: COMMAND
Memory before: [Turn1, Turn2, Turn3]  [FULL]
Memory after: [Turn2, Turn3, Turn4]  [Turn1 evicted]
```

---

## Interaction Record

Each stored interaction is an `InteractionRecord` with:

```python
@dataclass
class InteractionRecord:
    timestamp: datetime       # When this interaction occurred
    user_utterance: str      # What user said
    parsed_intent: str       # Classified intent (GREETING, QUESTION, etc.)
    generated_response: str  # System response
```

---

## Memory Inspection

### get_stats()

Returns diagnostic information:

```python
memory.get_stats()
# Returns:
{
    "capacity": 3,              # Max interactions
    "count": 2,                 # Current interactions
    "full": False,              # Is at capacity?
    "empty": False,             # Is empty?
    "session_age_seconds": 45.3 # Time since session started
}
```

### get_context_summary()

Returns human-readable summary for LLM prompts:

```
"Turn 1: You said 'Hello' (classified as GREETING). I responded 'Hi there!'. 
 Turn 2: You said 'What time is it?' (classified as QUESTION). I responded 'It's 3 PM'."
```

### get_recent_utterances(n=None)

Returns recent utterances (newest first):

```python
memory.get_recent_utterances()      # All utterances
memory.get_recent_utterances(n=2)   # Last 2 utterances
memory.get_recent_utterances(n=1)   # Most recent only
```

---

## Failure Modes Prevented by Bounded Design

### Mode 1: Context Explosion
**Problem**: Unbounded memory grows with each turn, eventually exhausting storage

**Prevention**: Fixed capacity ring buffer
- Memory never exceeds configured size (default 3)
- Old interactions automatically evicted
- O(1) space usage guaranteed

### Mode 2: Context Pollution
**Problem**: Ancient history pollutes LLM context, confusing responses

**Prevention**: Automatic eviction of oldest entries
- Only recent N interactions available
- Old context never mixes with new queries
- Fresh context always dominates

### Mode 3: Cross-Session Leakage
**Problem**: Previous session's memory affects next session

**Prevention**: Complete memory clear on program exit
- Sessions are truly independent
- No persistent state between runs
- No implicit context carryover

### Mode 4: Memory Modification
**Problem**: Different components modify memory inconsistently

**Prevention**: Read-only access for LLM
- ResponseGenerator cannot modify memory
- Only Coordinator appends
- No race conditions or conflicts
- Clear single source of truth

### Mode 5: Undetectable Memory State
**Problem**: No visibility into what memory contains

**Prevention**: Transparent design
- All memory operations logged
- get_stats() provides diagnostics
- get_context_summary() human-readable
- Complete inspection capabilities

---

## Implementation Details

### Ring Buffer

Uses Python's `deque` with `maxlen` parameter:

```python
from collections import deque

# Automatically evicts oldest when full
self.interactions = deque(maxlen=3)

self.interactions.append(record1)  # [record1]
self.interactions.append(record2)  # [record1, record2]
self.interactions.append(record3)  # [record1, record2, record3]  FULL
self.interactions.append(record4)  # [record2, record3, record4]  record1 evicted
```

### Thread Safety

NOT thread-safe. SessionMemory is:
- Single-threaded only
- Called from main thread only
- No locks or synchronization
- Not designed for concurrent access

This is fine because:
- Single user per session
- Coordinator runs sequentially
- No multi-threaded handlers
- All operations from main loop

---

## Testing

### Test Coverage

14 tests in `test_session_memory.py`:

1. ✅ Memory creation (starts empty)
2. ✅ Single append (add one interaction)
3. ✅ Multiple appends (add multiple interactions)
4. ✅ Fill to capacity (reach max)
5. ✅ Eviction (oldest removed when full)
6. ✅ Recent utterances order (newest first)
7. ✅ Recent responses order (newest first)
8. ✅ Context summary (human-readable)
9. ✅ Clear (empty all memory)
10. ✅ Stats (diagnostic info)
11. ✅ Capacity validation (reject invalid sizes)
12. ✅ Multiple sessions (independent memories)
13. ✅ Get n limit (partial retrieval)
14. ✅ Timestamps (interactions timestamped)

All 14 tests passing.

### Running Tests

```bash
python test_session_memory.py
```

Output:
```
============================================================
SESSION MEMORY TEST SUITE
============================================================

✅ test_memory_creation passed
✅ test_memory_append_single passed
...
✅ test_memory_interactions_contain_timestamp passed

============================================================
RESULTS: 14 passed, 0 failed out of 14 tests
============================================================
```

---

## Limitations & Future Directions

### Milestone 1 (v1.0.0 — Current)
✅ Session memory: Short-term, bounded, explicit, read-only for LLM
✅ Fixed capacity ring buffer
✅ No learning, no embeddings, no personality

### Milestone 2 (Future — Planned)
🔲 Persistent conversation history (optional, opt-in)
🔲 Longer session windows
🔲 Optional summary layer for very long sessions

### Milestone 3 (Future — Optional)
🔲 Preference tracking (if user requests)
🔲 Personalization layer (separate from core)

### Milestone 4 (Future — Optional)
🔲 Personality layer (if architecture evolves)
🔲 Character consistency
🔲 Relationship building

**Current design explicitly prevents**:
- ❌ Automatic learning
- ❌ Cross-session memory
- ❌ Embeddings or vector search
- ❌ Preference optimization
- ❌ Hidden state or implicit memory
- ❌ Personality traits

---

## Performance Characteristics

### Memory Usage

- **Per interaction**: ~500 bytes (text + metadata)
- **Total capacity (3 interactions)**: ~1.5 KB
- **Growth**: O(1) — fixed at capacity

### Access Speed

- **Append**: O(1) — constant time ring buffer
- **Get recent**: O(1) — deque copy operation
- **Context summary**: O(n) where n=capacity (usually 3)

### No Performance Degradation

- Memory never fills disk
- Lookup never slow (fixed size)
- Eviction never blocks
- No garbage collection pauses

---

## Security Implications

### What's Stored

- User utterances (spoken words)
- Classified intents (metadata)
- Generated responses (LLM output)

### What's NOT Stored

- ❌ Audio files
- ❌ Embeddings
- ❌ User profile data
- ❌ Preference history
- ❌ Cross-session data

### Privacy

- Memory is **cleared on exit** (no persistence)
- Only recent 3 interactions stored
- No external transmission
- No server-side backup

---

## Debugging

### Inspect Memory State

```python
coordinator.memory.get_stats()
# {
#     "capacity": 3,
#     "count": 2,
#     "full": False,
#     "empty": False,
#     "session_age_seconds": 120.5
# }

coordinator.memory.get_context_summary()
# "Turn 1: You said 'Hello' (classified as GREETING). I responded 'Hi there!'. ..."

coordinator.memory.get_all_interactions()
# [InteractionRecord(...), InteractionRecord(...)]
```

### Memory Logging

Coordinator logs memory state on each iteration:

```
[Loop] Memory: SessionMemory(capacity=3, count=2, full=False)
[Iteration 3] Memory updated: SessionMemory(capacity=3, count=3, full=True)
[Loop] Clearing SessionMemory...
[Loop] SessionMemory cleared: SessionMemory(capacity=3, count=0, full=False)
```

---

## Conclusion

Session Memory is the **minimal viable context window** for multi-turn interactions.

It's:
- ✅ Bounded (never grows)
- ✅ Transparent (completely visible)
- ✅ Temporary (cleared on exit)
- ✅ Explicit (no hidden state)
- ✅ Safe (read-only for LLM)
- ✅ Simple (no embeddings or summarization)

This design prevents the common failure modes of naive conversation systems while keeping the implementation understandable and maintainable.
