# Intent Artifact System

**Status:** v1.0.0 (Deterministic, Non-Executable)  
**Created:** January 2026  
**Creator:** Tommy Gunn (@tommygunn212)

---

## What Intent Artifacts Are

Intent Artifacts transform confirmed user input into structured intent candidates without executing anything.

### Pipeline

```
Audio/Text → Confirm → IntentArtifact → (future) ExecutableIntent → Action
             ✓          (pure parsing)     (approval only)         (future)
```

### Input Sources

IntentArtifacts ONLY come from:
- ✓ Confirmed typed input (user typed text directly)
- ✓ Confirmed TranscriptionArtifact (user approved audio transcript)

**No other sources allowed.**

### Structure

```python
artifact = IntentArtifact()

artifact.id                    # Unique UUID
artifact.timestamp             # ISO 8601 when parsed
artifact.source_type           # "typed" or "transcription"
artifact.source_artifact_id    # Reference to source
artifact.raw_text              # Original input (never discarded)
artifact.parsed_intent         # {verb, target, object, parameters, ambiguity}
artifact.confidence            # 0.0-1.0 (1.0 = clear, unambiguous)
artifact.status                # "proposed" | "rejected" | "approved"
artifact.requires_confirmation # Always True (invariant)
```

---

## What Intent Artifacts Explicitly Do NOT Do

**Intent Artifacts are NOT executable.**

They do NOT:
- ✗ Open applications
- ✗ Save files
- ✗ Create directories
- ✗ Trigger OS commands
- ✗ Send emails
- ✗ Execute shell scripts
- ✗ Modify system state
- ✗ Chain multiple intents
- ✗ Infer intent beyond grammar
- ✗ Bypass confirmation
- ✗ Produce side effects

**"Approved" means: "User said yes, this is what they meant."**
**NOT: "Execute this now."**

---

## Command Grammar (Minimal, Deterministic)

### Supported Verbs

- **write** — Create/compose text content
- **open** — Launch application or file
- **save** — Persist content
- **show** — Display information or content
- **search** — Query data

### Parsing Philosophy

- If ambiguous → **preserve ambiguity** (don't guess)
- If unparseable → **set low confidence**, keep raw_text
- Never infer missing fields
- No NLP magic, just pattern matching

### Parsing Output

```python
result = {
    "verb": "open",           # Recognized verb or None
    "target": "word",         # Primary object (app/file/content)
    "object": None,           # Secondary object (details/content)
    "parameters": {},         # Reserved for future expansion
    "ambiguity": [],          # List of ambiguity notes
    "confidence": 1.0         # 0.0-1.0 (1.0 = unambiguous)
}
```

### Examples

**Clear Parse:**
```
Input:  "open word"
Output: {
  "verb": "open",
  "target": "word",
  "object": None,
  "ambiguity": [],
  "confidence": 1.0
}
```

**Ambiguous Parse:**
```
Input:  "write something about climate"
Output: {
  "verb": "write",
  "target": None,
  "object": "about climate",
  "ambiguity": ["target unclear (missing recipient/type)"],
  "confidence": 0.8
}
```

**Unparseable:**
```
Input:  "please do something nice"
Output: {
  "verb": None,
  "target": None,
  "object": None,
  "ambiguity": ["no recognized verb"],
  "confidence": 0.0
}
```

---

## Confirmation Gate (User Approval Only)

Before an artifact advances from "proposed" state:

### User Flow

1. **ARGO displays:**
   ```
   Is this what you want to do?
   
   Raw text: "save as report.txt"
   
   Intent: {
     "verb": "save",
     "target": "report.txt",
     "confidence": 1.0
   }
   
   Approve? (yes/no):
   ```

2. **User confirms or rejects**
3. **Only explicit approval** advances status to "approved"
4. **No downstream processing** without approval

### Code Example

```python
from wrapper.intent import create_intent_artifact, intent_storage

# Create from confirmed source
artifact = create_intent_artifact(
    "save as report.txt",
    source_type="typed"
)

# Display for confirmation
print(f"Raw: {artifact.raw_text}")
print(f"Verb: {artifact.parsed_intent['verb']}")
print(f"Confidence: {artifact.confidence:.0%}")

# Get user approval
response = input("Approve? (yes/no): ").strip().lower()

if response in ["yes", "y"]:
    intent_storage.approve(artifact.id)
    # Now safe for future execution layer
else:
    intent_storage.reject(artifact.id)
    print("Rejected. Please try again.")
```

---

## Storage (Session-Only, Inspectable)

### Properties

- **Session-only**: Artifacts held in memory, not auto-saved
- **Inspectable**: List all artifacts for audit and replay
- **No silent deletion**: All state changes logged

### API

```python
from wrapper.intent import intent_storage, create_intent_artifact

# Create and store
artifact = create_intent_artifact("open word", source_type="typed")
intent_storage.store(artifact)

# Retrieve
artifact = intent_storage.retrieve(artifact.id)

# Confirm/reject
intent_storage.approve(artifact.id)
intent_storage.reject(artifact.id)

# List by status
proposed = intent_storage.list_proposed()  # pending approval
approved = intent_storage.list_approved()  # user approved
all_artifacts = intent_storage.list_all()  # everything
```

---

## Logging and Auditability

All events logged to `runtime/logs/intent.log`:

```
2026-01-17T14:45:32.123456Z - INTENT - INFO - [artifact-id] Created IntentArtifact from typed source. Verb: open. Confidence: 1.00. Status: proposed
2026-01-17T14:45:33.234567Z - INTENT - INFO - Parsed: verb=open target=word object=None confidence=1.00 ambiguity=0
2026-01-17T14:45:34.345678Z - INTENT - INFO - Approved artifact: artifact-id
```

---

## Architecture in System Context

### Full Pipeline (Current + Future)

```
User Input (Audio/Text)
    ↓
[Transcription Layer] ← Whisper transcription with confirmation
    ↓
Confirmed Text
    ↓
[Intent Layer] ← YOU ARE HERE
    ↓
Structured Intent (proposed)
    ↓
[Confirmation Gate] ← "Is this what you want?"
    ↓
Approved Intent
    ↓
[Executable Intent Layer] ← FUTURE (not yet implemented)
    ↓
[Execution Engine] ← FUTURE (not yet implemented)
    ↓
Action (with audit trail)
```

### What Each Layer Does

| Layer | Input | Output | Side Effects |
|-------|-------|--------|--------------|
| Transcription | Audio file | TranscriptionArtifact | None |
| Intent (current) | Confirmed text | IntentArtifact | Logging only |
| Executable Intent | Approved artifact | ExecutableIntent plan | None (planning only) |
| Execution | ExecutableIntent | Result | File/app/network changes |

---

## Design Principles

### 1. Determinism
Same text always produces same artifact (no randomness).

### 2. No Guessing
Ambiguity is preserved, never inferred.

### 3. Non-Execution
Status changes are the ONLY side effect.

### 4. Auditability
Every parse and confirmation logged.

### 5. User Control
Only explicit "yes" advances state.

### 6. Source Validation
Only confirmed inputs allowed.

---

## Testing Strategy

### Covered Scenarios

✓ **Clean parses:** Clear input, unambiguous result, high confidence  
✓ **Ambiguous input:** Multiple interpretations, preserved in artifact  
✓ **Unparseable input:** No recognized verb, low confidence  
✓ **Confirmation gate:** Approval/rejection tracked  
✓ **Storage:** Retrieve, list, state management  
✓ **NO EXECUTION:** Verified no side effects  

### What's NOT Tested

❌ File creation (would be execution)  
❌ App launching (would be execution)  
❌ OS commands (would be execution)  
❌ Network operations (would be execution)  

---

## Usage

### Create and Confirm Artifact

```python
from wrapper.intent import create_intent_artifact, intent_storage

# From typed input
artifact = create_intent_artifact(
    "open word",
    source_type="typed"
)

# From transcription (after Whisper confirmation)
artifact = create_intent_artifact(
    confirmed_transcript,
    source_type="transcription",
    source_artifact_id=transcript_artifact.id
)

# Display for user approval
print(f"Artifact ID: {artifact.id}")
print(f"Raw text: {artifact.raw_text}")
print(f"Intent: {artifact.parsed_intent}")
print(f"Confidence: {artifact.confidence:.0%}")

if user_approves:
    intent_storage.approve(artifact.id)
```

### List and Inspect

```python
from wrapper.intent import intent_storage

# What's pending?
pending = intent_storage.list_proposed()
for artifact in pending:
    print(f"{artifact.id}: {artifact.raw_text}")

# What's approved?
approved = intent_storage.list_approved()
for artifact in approved:
    print(f"APPROVED: {artifact.parsed_intent['verb']}")
```

---

## Future Extension Points

This design is a foundation for:

1. **Executable Intent Layer** (non-breaking extension)
   - Takes approved IntentArtifacts
   - Builds execution plans
   - Still no execution

2. **Execution Engine** (non-breaking extension)
   - Takes ExecutableIntents
   - Performs actions with full audit trail
   - Rollback on failure

3. **Multi-Intent Chaining** (future phase)
   - Parse multiple intents per input
   - Track dependencies
   - Execute in order

4. **Intent Refinement** (future phase)
   - User clarifies ambiguous intents
   - Parser learns from feedback
   - Confidence improves

---

## FAQ

**Q: Why no execution in this layer?**  
A: Separation of concerns. Parsing and planning are low-risk. Execution is high-risk. Keep them separate.

**Q: Can artifacts be chained?**  
A: Not in Phase 1. Single intent per artifact. Future phase will support chaining.

**Q: What if I modify an artifact?**  
A: Go ahead—it's in memory. Status doesn't auto-advance unless you call `approve()`. Changes are logged.

**Q: Can I save artifacts to disk?**  
A: Not in this layer. They're session-only. If you want persistence, that's a future phase.

**Q: What happens if confidence is 0.0?**  
A: Artifact is still stored, still confirmable. User can approve even low-confidence parses (means they're overriding the parser).

**Q: Is this machine learning?**  
A: No. Pure pattern matching. Grammar-based, not neural.

---

## References

- [Whisper Transcription](../transcription/whisper.md) — Audio confirmation
- [ARGO Architecture](../architecture/architecture.md) — System design
- Test suite: [test_intent_artifacts.py](../../test_intent_artifacts.py)
