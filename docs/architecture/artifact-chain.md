# ARGO Artifact Chain Architecture

**Status:** Foundational Design (v1.0+)  
**Last Updated:** January 17, 2026  
**Classification:** Architecture Constitution

---

## Core Principle

**Each artifact answers ONE question, then stops.**

This single principle is the foundation of ARGO's safety model. Most systems fail because they answer two questions at once and pretend they didn't. We don't.

---

## Critical Design Invariants

These are not guidelines. They are enforced rules.

### Invariant 1: No Confirmation, No Advancement

**No artifact may be created or advanced without explicit human confirmation.**

```
TranscriptionArtifact (pending_confirmation) 
    → User confirms → status: confirmed
    → User rejects → artifact discarded

IntentArtifact (pending_confirmation)
    → User confirms → status: approved
    → User rejects → artifact discarded

ExecutionPlanArtifact (pending_confirmation)
    → User confirms → status: awaiting_execution
    → User rejects → artifact discarded
```

No automatic advancement. No timeout-based escalation. No "proceed anyway" paths.

### Invariant 2: Session-Only Ephemeral Storage

**Artifacts never persist across restarts unless explicitly promoted.**

```
Session 1:
  TranscriptionArtifact (confirmed)
  IntentArtifact (approved)
  ExecutionPlanArtifact (awaiting_execution)
  
Session ends → All three artifacts cleared from memory

Logs recorded:
  runtime/logs/transcription.log (permanent)
  runtime/logs/intent.log (permanent)
  runtime/logs/executable_intent.log (permanent)

Session 2:
  No artifacts loaded
  Clean slate
  Logs available for review/replay
```

This prevents "but it remembered" surprises and maintains transparency about system state.

### Invariant 3: Linear Information Flow

**Each layer's output becomes the next layer's input. No backtracking. No lateral jumps.**

```
Audio
  ↓ (Whisper)
TranscriptionArtifact (confirmed)
  ↓ (Intent Parser)
IntentArtifact (approved)
  ↓ (Plan Deriver)
ExecutionPlanArtifact (awaiting_execution)
  ↓ (v1.3.0+: Execution Engine)
Executed Actions + Audit Log
```

No shortcuts. No "skip intent parsing and go straight to execution." No mixing confirmed and unconfirmed data streams.

---

## The Three Artifact Layers

### Layer 1: TranscriptionArtifact (v1.0.0)

**Question Answered:** "What did the user say?"

```
Input:  audio.wav
Output: TranscriptionArtifact {
          id: "trans_abc123",
          raw_audio: "path/to/audio.wav",
          transcribed_text: "Write my report",
          model: "openai/whisper-base",
          confidence: 0.94,
          timestamp: "2026-01-17T18:15:42",
          source: "transcription",
          status: "pending_confirmation"
        }

Confirmation Gate:
  User sees: "I heard: 'Write my report'. Correct? [yes/no]"
  
  If yes → status: confirmed
  If no  → artifact discarded, ask again
```

**What It Does NOT Do:**
- ❌ Parse intent
- ❌ Execute anything
- ❌ Auto-advance to next layer
- ❌ Interpret what the user meant
- ❌ Make assumptions about action

**What You Get:**
- ✅ Exact text transcribed
- ✅ Confidence score
- ✅ Full auditability
- ✅ User sees what was heard
- ✅ Human confirmation required

**Logs:** `runtime/logs/transcription.log` (permanent)

---

### Layer 2: IntentArtifact (v1.1.0)

**Question Answered:** "What did the user mean?"

```
Input:  confirmed_text ("Write my report")
Output: IntentArtifact {
          id: "intent_def456",
          raw_text: "Write my report",
          parsed_intent: {
            verb: "write",
            target: "report",
            object: "current_directory",
            parameters: {...},
            ambiguity: ["Overwrite existing report?", "Which format?"]
          },
          confidence: 0.87,
          source: "typed" | "transcription",
          status: "pending_confirmation"
        }

Confirmation Gate:
  User sees: Parsed intent in JSON
             "Verb: write, Target: report. Proceed? [yes/no]"
  
  If yes → status: approved
  If no  → artifact discarded, ask again
```

**What It Does NOT Do:**
- ❌ Execute anything
- ❌ Create files
- ❌ Launch applications
- ❌ Auto-advance to next layer
- ❌ Guess about ambiguity (preserves it instead)

**What You Get:**
- ✅ Structured intent (verb, target, object)
- ✅ Ambiguity preserved (never inferred)
- ✅ Confidence score
- ✅ Full auditability
- ✅ Human confirmation required
- ✅ Clean handoff to planning layer

**Logs:** `runtime/logs/intent.log` (permanent)

---

### Layer 3: ExecutionPlanArtifact (v1.2.0)

**Question Answered:** "How will we do it safely?"

```
Input:  approved_intent (IntentArtifact)
Output: ExecutionPlanArtifact {
          plan_id: "plan_ghi789",
          intent_id: "intent_def456",
          intent_text: "Write my report",
          
          steps: [
            {
              step_id: 1,
              action_type: "query",
              operation: "check_exists",
              target: "report.txt",
              safety_level: "safe",
              rollback_capability: "full"
            },
            {
              step_id: 2,
              action_type: "create",
              operation: "backup_existing",
              target: "report.txt.backup",
              safety_level: "cautious",
              rollback_capability: "full",
              rollback_procedure: "Restore from report.txt.backup"
            },
            {
              step_id: 3,
              action_type: "write",
              operation: "write_file",
              target: "report.txt",
              safety_level: "cautious",
              rollback_capability: "full",
              required_confirmations: ["confirm_overwrite"]
            }
          ],
          
          highest_risk_level: "cautious",
          total_confirmations_needed: 1,
          can_fully_rollback: true,
          status: "pending_confirmation"
        }

Confirmation Gate:
  User sees: Plan summary with steps, risks, rollback info
             "This plan needs 1 confirmation. Risk level: cautious.
              Reversible: yes. Proceed? [yes/no]"
  
  If yes → status: awaiting_execution
  If no  → artifact discarded, offer alternatives
```

**What It Does NOT Do:**
- ❌ Execute anything
- ❌ Create files
- ❌ Launch applications
- ❌ Auto-advance to execution
- ❌ Assume user will approve

**What You Get:**
- ✅ Step-by-step decomposition
- ✅ Risk analysis (SAFE, CAUTIOUS, RISKY, CRITICAL)
- ✅ Rollback procedures defined
- ✅ Confirmation counts
- ✅ Full auditability
- ✅ Human confirmation required
- ✅ Ready for execution layer (v1.3.0+)

**Logs:** `runtime/logs/executable_intent.log` (permanent)

---

## The Complete Chain

```
┌──────────────────────────────────────────────────────────────┐
│                    USER INPUT (Audio or Text)                │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ↓
        ┌──────────────────────────────┐
        │  v1.0.0: TRANSCRIPTION LAYER │
        │  Audio → TranscriptionArtifact│
        │  (Whisper, no interpretation)│
        └──────────────┬────────────────┘
                       │
        USER CONFIRMS: "That's what I said"
                       │
                       ↓
        ┌──────────────────────────────┐
        │    v1.1.0: INTENT LAYER      │
        │  Text → IntentArtifact       │
        │  (Grammar parsing only)      │
        └──────────────┬────────────────┘
                       │
        USER CONFIRMS: "That's what I meant"
                       │
                       ↓
        ┌──────────────────────────────┐
        │   v1.2.0: PLANNING LAYER     │
        │  Intent → ExecutionPlanArtifact
        │  (Derivation, no execution)  │
        └──────────────┬────────────────┘
                       │
        USER CONFIRMS: "Execute that plan"
                       │
                       ↓
        ┌──────────────────────────────┐
        │ v1.3.0+: EXECUTION LAYER     │
        │ ExecutionPlanArtifact → Do it│
        │ [NOT YET IMPLEMENTED]        │
        └──────────────────────────────┘
```

---

## Why This Matters

### Problem: Monolithic Systems

**Traditional approach:**
```
Audio → [Magic] → Action

User has no visibility into:
  - What was transcribed
  - What was understood
  - What will happen
  - Why it's happening
```

**Result:** Trust fails. Users don't know if system misbehaved or they mispoke.

### Solution: Artifact Layers

**ARGO approach:**
```
Audio → TranscriptionArtifact ✅ (User confirms)
  ↓
Text → IntentArtifact ✅ (User confirms)
  ↓
Intent → ExecutionPlanArtifact ✅ (User confirms)
  ↓
Plan → Executed ✅ (Audit trail complete)
```

**Result:** 
- User sees exactly what system understood at each stage
- User explicitly approves before advancing
- System behavior is deterministic and auditable
- Failures are traceable to specific layer

---

## Properties Across All Layers

| Property | Guarantee |
|----------|-----------|
| **Auditable** | Every artifact is logged with timestamp, source, and decision |
| **Deterministic** | Same input always produces same artifact structure |
| **User-Controlled** | Explicit confirmation required before advancement |
| **Non-Executing** | No side effects during artifact creation |
| **Reversible** | Rollback procedures defined in execution plan |
| **Session-Isolated** | Artifacts ephemeral, logs permanent, clean restart each session |
| **Layered** | Each layer answers one question and stops |

---

## No Execution Paths

This is critical: there is **no way** for an artifact to advance without explicit human confirmation.

```
Confirmation Gate 1: TranscriptionArtifact
  ❌ No timeout-based auto-advance
  ❌ No "proceed anyway" override
  ❌ No silent fallback
  ✅ Explicit yes/no only

Confirmation Gate 2: IntentArtifact
  ❌ No automatic intent inference
  ❌ No "skip if confident" logic
  ❌ No background learning that skips confirmation
  ✅ Explicit approval only

Confirmation Gate 3: ExecutionPlanArtifact
  ❌ No "this seems safe, run it" logic
  ❌ No automatic safety override
  ❌ No "user will approve anyway" assumptions
  ✅ Explicit approval only
```

---

## Session Lifecycle

### Session Start

```
Session ID: uuid4()
Start time: now
Artifacts: {} (empty)
Logs: Open file handles
```

### During Session

```
User input → TranscriptionArtifact (pending)
User confirms → status: confirmed
           ↓
Text → IntentArtifact (pending)
User confirms → status: approved
           ↓
Intent → ExecutionPlanArtifact (pending)
User confirms → status: awaiting_execution
           ↓
(v1.3.0+) Execute and log results
```

All artifacts held in memory. All logs written to files.

### Session End

```
Session end: now
Artifacts in memory: Cleared
Logs on disk: Preserved

Next session:
  New session ID
  New artifact storage
  Logs available for review (read-only)
```

No persistence. No "it remembered from last time." No state leakage between sessions.

---

## Invariants as Constraints

These rules are enforced by design:

### Enforcement: No Artifact Without Confirmation

```python
# In each artifact module:

class IntentArtifact:
    def __init__(self, ...):
        self.status = "pending_confirmation"  # Always starts here
        # No way to advance without external confirmation
    
    def confirm(self):
        """Only way to advance"""
        # User called this explicitly
        self.status = "approved"

# No auto-advancement. No background processes. Only explicit user call.
```

### Enforcement: Session-Only Storage

```python
class ArtifactStorage:
    def __init__(self):
        self.artifacts = {}  # In-memory only
        # No persistent database
        # No cache that survives restarts
    
    def clear_session(self):
        """Called on shutdown"""
        self.artifacts.clear()  # Everything gone
```

### Enforcement: Logs Are Separate

```python
# Artifacts: ephemeral
artifacts = artifact_storage.list()  # Empty after restart

# Logs: permanent
with open("runtime/logs/intent.log") as f:
    history = f.read()  # Full record preserved
```

---

## What This Unlocks

Because this architecture is now written and frozen:

### 1. Deterministic Execution (v1.3.0+)

Execution engine can trust that ExecutionPlanArtifacts are:
- Complete (all steps defined)
- Verified (all safety levels assigned)
- Auditable (full log trail exists)
- Approved (user confirmed)

No edge cases. No "what if the artifact is malformed?" No defensive coding.

### 2. Reversible Actions

Rollback procedures are defined in the plan:

```
Plan says: "If this write fails, restore from report.txt.backup"
Execution layer: "Okay, I know how to undo this"
```

No panic. No "how do we fix this?" Rollback is pre-planned.

### 3. Safe OS and Smart Home Control

Because we know:
- What will happen (ExecutionPlanArtifact)
- Why it will happen (user confirmed it)
- How to undo it (rollback procedure defined)
- What changed (audit log)

We can safely control:
- File system operations
- Application launching
- Device control (Raspberry Pi)
- Smart home actions

### 4. Safe "No" By Default

The system naturally says "no" without sounding broken:

```
System: "I need your approval to: [steps]. Confirm? [y/n]"
User: "No"
System: "Understood. No changes made."
```

This is normal. Expected. Not an error.

### 5. Upstream Stability

You never need to refactor Whisper or Intent again.

- Whisper outputs TranscriptionArtifact (frozen format)
- Intent outputs IntentArtifact (frozen format)
- Both are upstream

Execution layer (v1.3.0+, v2.0.0+) adapts downstream to consume these formats.

**This is how grown systems age.**

---

## What This Prevents

### No Silent Execution

```
❌ Bad: "Device was turned off silently"
✅ Good: "Plan requires confirmation before turning off device"
```

### No Magic Inference

```
❌ Bad: "System guessed you meant X because it's confident"
✅ Good: "System found ambiguity X. User confirms intended meaning."
```

### No State Surprise

```
❌ Bad: "Device was on last time; must still be on"
✅ Good: "Each session starts clean. Current state unknown until queried."
```

### No Background Learning

```
❌ Bad: "System learned your preference and applied it"
✅ Good: "User explicitly set preference in this session"
```

### No Unseen Changes

```
❌ Bad: "You're logged in; I'll handle this for you"
✅ Good: "I need your approval before making changes"
```

---

## Testing This Architecture

### Test Coverage Across Layers

Each layer tests:

1. **Artifact Creation**
   - Does artifact initialize correctly?
   - Is status always "pending_confirmation"?
   - Are all fields populated?

2. **No Auto-Advancement**
   - Confirm the artifact does NOT auto-advance
   - Confirm no background process advances it
   - Confirm manual call is required

3. **Confirmation Gate**
   - Confirm gate works (yes/no)
   - Confirm rejection discards artifact
   - Confirm approval advances status

4. **Audit Trail**
   - Confirm all artifacts logged
   - Confirm logs survive session end
   - Confirm logs are read-only

5. **Session Isolation**
   - Confirm artifacts cleared on shutdown
   - Confirm new session gets clean state
   - Confirm logs still accessible

### Critical Test: No Execution

For each layer, test that:

```python
artifact = create_artifact(input)
# Verify: no files created
# Verify: no applications launched
# Verify: no system state changed
# Verify: no network requests
```

This test MUST pass. If it fails, the architecture is broken.

---

## Documentation Standard

This document is a **constitution**, not a blog post.

Changes to this document require:
1. Understanding of all downstream implications
2. Backward compatibility analysis
3. Updates to all affected layers
4. New tests verifying the change

Casual rewrites are not permitted. This document defines the system's foundation.

---

## References

- [MILESTONES.md](../../MILESTONES.md) — Project completion status
- [wrapper/transcription.py](../../wrapper/transcription.py) — TranscriptionArtifact implementation
- [wrapper/intent.py](../../wrapper/intent.py) — IntentArtifact implementation
- [wrapper/executable_intent.py](../../wrapper/executable_intent.py) — ExecutionPlanArtifact implementation
- [ARCHITECTURE.md](../../ARCHITECTURE.md) — System-level architecture
