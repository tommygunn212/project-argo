# Intent Execution Specification

**Document Type**: Design Specification (Not Implementation)  
**Status**: Design Phase - Execution Layer Boundary Definition  
**Date**: 2026-01-15  
**Purpose**: Define safe execution boundaries before any execution code exists

---

## Purpose

**What execution is allowed to do:**

1. Read approved intent ID from caller
2. Verify hash against approved.jsonl
3. If verification passes, signal approval to caller
4. That's it

**What execution is explicitly forbidden from doing:**

❌ Execute tools or commands  
❌ Modify intent queue files  
❌ Create new intents  
❌ Delete, rename, or archive intent records  
❌ Infer intent meaning from hash  
❌ Reconstruct original intent text  
❌ Auto-approve any intent  
❌ Proceed if any verification step fails  
❌ Log raw intent content  
❌ Make decisions about safety  
❌ Integrate with ARGO tools (yet)  
❌ Execute based on intent content (that's ARGO's job, later)  

**What execution actually is:**

A **pass/fail gate**. Nothing more.

```
Input: intent_id, hash
Verify: intent_id exists in approved.jsonl
Verify: stored_hash == provided_hash
Output: "APPROVED" (exit 0) or "DENIED" (exit 1)
```

---

## Inputs

### Source of Truth

Only one source is authoritative:

**approved.jsonl**
- Location: I:\argo\intent_queue\approved.jsonl
- Format: JSON Lines (one JSON object per line)
- Content per line: `{"id": "uuid", "timestamp": "iso", "hash": "sha256"}`
- No other files consulted
- No caching
- No in-memory copies

### What the Execution Layer Receives

**Input 1: Intent ID (UUID)**
- Format: standard UUID (36 chars, lowercase, hyphens)
- Source: command-line argument or stdin
- Validation: Must be valid UUID format or fail immediately
- Example: `b2831d73-2708-4f50-944b-7b54f11bfbb4`

**Input 2: Intent Hash (SHA256)**
- Format: hex string, 64 characters
- Source: command-line argument or stdin
- Validation: Must be 64-character hex string or fail immediately
- Example: `d74524813b020264...` (full 64 chars)
- Purpose: Verify intent has not changed since approval

### Hash Verification Process

1. **Accept inputs**: intent_id and hash_to_verify
2. **Open approved.jsonl**: Read entire file (append-only, no seek)
3. **Parse each line**: Extract {"id", "hash"} from JSON
4. **Find match**: Look for line where id == intent_id
5. **If found**:
   - Compare provided hash with stored hash (byte-by-byte)
   - If match: return "APPROVED" (exit 0)
   - If mismatch: return "HASH MISMATCH" (exit 1)
6. **If not found**: return "NOT APPROVED" (exit 1)
7. **File error**: return "VERIFICATION FAILED" (exit 1)

### Critical Constraint

**Never reconstruct original text from hash.**

Hashes are one-way. If verification passes, the system knows:
- An intent was approved
- It had a specific hash
- Original text is irrelevant

The system does NOT need to know what the intent said. That's ARGO's problem (next layer).

---

## Preconditions

### Exact Checks Required Before Execution

**Check 1: Intent ID Format**
```
If intent_id is not valid UUID format:
    Exit 1, print "[ERROR] Invalid intent ID format"
```

**Check 2: Hash Format**
```
If hash is not 64-character hex string:
    Exit 1, print "[ERROR] Invalid hash format"
```

**Check 3: approved.jsonl Exists**
```
If I:\argo\intent_queue\approved.jsonl does not exist:
    Exit 1, print "[ERROR] Approved queue not initialized"
```

**Check 4: approved.jsonl Readable**
```
If file cannot be opened for reading:
    Exit 1, print "[ERROR] Cannot read approved queue"
```

**Check 5: Hash Match**
```
If intent_id in approved.jsonl:
    If stored_hash != provided_hash:
        Exit 1, print "[ERROR] Hash mismatch - intent may have been modified"
    Else:
        Exit 0, print "[OK] Intent approved: <intent_id>"
Else:
    Exit 1, print "[ERROR] Intent not in approved queue"
```

### What Causes Immediate Hard Fail

Any of these conditions causes immediate hard failure (exit 1, clear message):

- ❌ Invalid UUID format
- ❌ Invalid hash format
- ❌ approved.jsonl missing
- ❌ approved.jsonl unreadable
- ❌ JSON parsing error on any line
- ❌ Intent ID not found in approved.jsonl
- ❌ Hash mismatch
- ❌ Any unexpected exception

**Never proceed if any check fails. Never default to approval.**

---

## Execution Boundary

### Where Execution Starts

**Input boundary**: Approved intent UUID and hash provided

Caller (human or ARGO layer) provides:
```
intent_id: "b2831d73-2708-4f50-944b-7b54f11bfbb4"
hash: "d74524813b020264..."
```

Execution layer begins here.

### Where It Must Stop

**Output boundary**: Pass/fail signal only

Execution layer returns:
- Exit code 0: Intent approved, ARGO can proceed
- Exit code 1: Intent not approved, ARGO stops

Execution layer does NOT:
- Call ARGO tools
- Load ARGO functions
- Read tool definitions
- Parse intent content
- Make tool selection decisions
- Execute anything

### What It Is Not Allowed to See, Load, Infer, or Reconstruct

❌ Original intent text (it's hashed for a reason)  
❌ Tool definitions from ARGO  
❌ Tool registry or capabilities  
❌ Intent history or patterns  
❌ User identity or preferences  
❌ Timestamps (only for audit, not for logic)  
❌ Related intents in queue  
❌ System state or configuration  
❌ Secrets or credentials  

If it needs any of these to make a decision, the boundary is wrong.

---

## Failure Modes

### Mode 1: Missing Approval

**Scenario**:
```
intent_id provided: "12345678-1234-1234-1234-123456789012"
approved.jsonl checked: ID not found
```

**Behavior**:
```
[ERROR] Intent not in approved queue: 12345678-1234-1234-1234-123456789012
Exit 1
```

**Follow-up**: Caller must retry with intent that WAS approved. No fallback, no retry in execution layer.

### Mode 2: Hash Mismatch

**Scenario**:
```
intent_id provided: "b2831d73-2708-4f50-944b-7b54f11bfbb4"
hash provided:      "d74524813b020264..."
stored hash:        "deadbeefdeadbeef..."
```

**Behavior**:
```
[ERROR] Hash mismatch - intent may have been modified
Stored:  deadbeefdeadbeef...
Provided: d74524813b020264...
Exit 1
```

**What this means**: Either:
- Intent text changed since approval (bad)
- Wrong intent ID passed (typo)
- Queue corrupted (worse)

All cases: Fail closed, ask human.

### Mode 3: Replay Attempt

**Scenario**:
```
intent_id: "b2831d73-2708-4f50-944b-7b54f11bfbb4"
[Intent was approved, executed, now retried]
```

**Behavior**:
```
[OK] Intent approved: b2831d73-2708-4f50-944b-7b54f11bfbb4
Exit 0
```

**Note**: Execution layer cannot prevent replay. It only verifies approval.

**Prevention happens at**: ARGO tool layer (execution controller must track which intents have been executed).

Execution layer is not responsible for preventing replay.

### Mode 4: Partial State

**Scenario**:
```
approved.jsonl partially written
Last line is incomplete JSON
```

**Behavior**:
```
[ERROR] Malformed entry in approved queue (line N)
Exit 1
```

**Prevention**: All writes to approved.jsonl must be atomic (write to temp file, move to approved.jsonl).

Intent queue layer (intent_queue.py, intent_review.py) must guarantee atomic writes.

### Mode 5: Anything Ambiguous

**Rule**: If the execution layer cannot definitively determine "approved" or "not approved", it fails closed.

Examples of ambiguous:

- Intent ID is UUID format but corrupted (exit 1)
- Hash format is wrong (exit 1)
- File is missing (exit 1)
- File is corrupted (exit 1)
- Intent exists but hash disagrees (exit 1)
- Any exception not explicitly handled (exit 1)

**Never guess. Never proceed when uncertain.**

---

## Non-Goals

**This execution spec is NOT about:**

❌ Retries  
❌ Automation  
❌ Batching  
❌ Background execution  
❌ Convenience  
❌ Performance optimization  
❌ Parallel processing  
❌ Caching  
❌ Smart fallbacks  
❌ Inferring user intent  
❌ Making decisions  
❌ Security hardening beyond hash verification  

**Why not these?**

**Retries**: If approval verification fails, caller should manually investigate, not auto-retry.

**Automation**: Every step is manual for now. If we want automation later, add a scheduler layer, don't hide it here.

**Batching**: One intent at a time. Simplicity now, parallelism later if needed.

**Background execution**: One-shot, synchronous, blocking. If we need async, that's a separate layer.

**Convenience**: Friction is intentional. Latency doesn't matter (one-shot system, seconds not milliseconds).

**Performance**: This is single-threaded, simple verification. If it becomes a bottleneck (extremely unlikely for one-shot system), optimize then, not now.

---

## Human Role

### What the Human Must Still Do Manually

1. **Run intent_queue.py**: Human captures voice intent and queues it
2. **Wait**: Human decides when approval time has come (minutes to days)
3. **Run intent_review.py**: Human reviews queued intent, types UUID to approve
4. **Provide intent_id and hash**: Human passes approved intent to execution layer
5. **Trigger execution**: Human runs ARGO with approved intent (not yet implemented)
6. **Verify result**: Human checks that action actually happened as expected

### What the System Must Never Do for Them

❌ Auto-approve intents  
❌ Auto-execute after time passes  
❌ Infer what human probably meant  
❌ Skip confirmation steps  
❌ Retry silently  
❌ Make assumptions about intent  
❌ Batch multiple intents  
❌ Schedule execution  

Every step requires human decision. System just verifies, doesn't decide.

---

## Absolute Rules for Intent Execution

### Rule 1: Verification Only

Execution layer is a **verifier**, not an executor.

It answers exactly one question: "Is this intent approved?"

It does not answer:
- "What should this intent do?"
- "Is this intent safe?"
- "How should this be executed?"
- "Should I execute it?"

Those are ARGO's questions (next layer, not this layer).

### Rule 2: Append-Only Source of Truth

Only approved.jsonl is consulted. Not pending.jsonl. Not any other file.

If it's not in approved.jsonl, it's not approved. Period.

### Rule 3: Hash Verification is Immutable

If hash doesn't match, execution fails. No exceptions, no overrides.

Hash mismatch could mean intent text changed. Could mean corruption. Could mean typo. All cases: fail closed.

### Rule 4: No Reconstruction

Never attempt to recreate original intent text from hash.

If execution needs to know what the intent said, execution layer is the wrong place for that question.

### Rule 5: Fail Closed

If anything is ambiguous, unclear, or wrong, exit 1 immediately.

Better to deny a legitimate intent than execute an illegitimate one.

### Rule 6: No Side Effects

Verification has no side effects. Reading approved.jsonl does not:
- Modify files
- Create logs
- Update state
- Send network requests
- Load configurations
- Call other functions

It only reads and compares.

### Rule 7: Single Responsibility

Execution layer does one thing: verify approval.

If it starts doing second thing (e.g., "also check if intent is safe"), boundary is wrong.

### Rule 8: Fail Fast

If any precondition fails, exit immediately with clear message.

Do not proceed to next step. Do not try to recover.

---

## Integration Points (Not Yet Implemented)

### Where Execution Layer Connects to ARGO

**Future flow** (not today):

```
Human: approves intent in intent_review.py
       Gets: intent_id and hash

ARGO is called with:
  python argo.py --approved-intent <intent_id> --hash <hash>

ARGO does:
  1. Call execution layer for verification
  2. If exit 0: proceeds to tool execution
  3. If exit 1: stops with error

ARGO then selects tool and executes
  (that's ARGO's job, not execution layer's)
```

**Separation of concerns**:

| Layer | Responsibility |
|-------|---|
| Intent Queue | Record intent, delay action |
| Intent Review | Human approval gate |
| **Execution** | **Verify approval only** |
| ARGO Tools | Actually execute commands |

Each layer has one job. Execution's job: "Is it approved?"

---

## Summary: What This Spec Defines

This specification defines the **execution verification boundary** without implementing anything.

**It answers**:
- What can execution layer do? (Verify approval)
- What must it never do? (Execute anything)
- What inputs does it accept? (intent_id, hash)
- Where does it stop? (After yes/no decision)
- What makes it fail? (Any ambiguity)
- What's the human's role? (Provide intent and approval)

**It does NOT**:
- Write code
- Refactor existing code
- Optimize performance
- Design future features
- Create shortcuts

**Next steps** (if requested):
1. Implement intent_execute.py based on this spec
2. Test execution verification
3. Integrate with ARGO (only after testing)
4. Add batch processing (only if one-shot becomes bottleneck)

**For now**: Spec only. Commit the doc. Stop.
