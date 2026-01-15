# ARGO Execution Controller Specification

**Document Type**: Design Specification (Not Implementation)  
**Status**: Design Phase - Execution Control Boundary Definition  
**Date**: 2026-01-15  
**Purpose**: Define the gate between approval and action

---

## 1. Purpose

**What the controller is responsible for:**

1. Receive approved intent UUID and hash from human-triggered ARGO invocation
2. Call intent_execute.py to verify approval
3. Interpret verification result
4. Check if execution is eligible (not already executed)
5. Signal to ARGO: "proceed" or "stop"
6. Nothing else

**What it is explicitly NOT responsible for:**

❌ Executing tools or commands  
❌ Parsing intent text  
❌ Making safety decisions  
❌ Inferring user intent  
❌ Selecting which tool to run  
❌ Retrying failed verifications  
❌ Scheduling execution  
❌ Creating or modifying intent records  
❌ Determining what the intent meant  
❌ Auto-recovering from ambiguity  
❌ Handling background execution  

**Key principle:**

**Approval verification and execution eligibility are separate from execution itself.**

Verification answers: "Is this intent approved?"  
Eligibility answers: "Has this intent already been executed?"  
Execution answers: "Run tool X with intent Y" (that's ARGO's job, not this layer's)

This controller handles the first two questions only.

---

## 2. Inputs

**Source**: Human-triggered ARGO invocation only

The controller receives exactly three inputs from the caller (human or ARGO interface):

**Input 1: Approved Intent UUID**
- Format: Standard UUID (36 chars, hex + hyphens)
- Source: Human provides after approval in intent_review.py
- Validation: Format must be valid UUID or halt immediately
- Example: `b2831d73-2708-4f50-944b-7b54f11bfbb4`

**Input 2: Intent Hash (SHA256)**
- Format: Hex string, 64 characters
- Source: Returned from intent_review.py (same as stored in approved.jsonl)
- Validation: Format must be 64-char hex or halt immediately
- Purpose: Verify intent has not changed since approval
- Example: `d74524813b020264a1b9e1f35b9c01f2f5cd01233e1f48e0ce5a7f14d8d1a9b0`

**Input 3: Invocation Source**
- Type: Human-triggered manual execution only
- Means: No background daemons, schedulers, or automatic retries
- Constraint: Each execution attempt requires human action
- No automated re-queuing
- No silent retry loops

---

## 3. Preconditions

### Checks Required Before Any Decision

**Precondition 1: intent_execute.py Exists**
```
If I:\argo\intent_execute.py does not exist:
    Halt immediately with error
    Exit 1
    Message: "[ERROR] Execution verification tool not found"
```

**Precondition 2: intent_execute.py is Callable**
```
If intent_execute.py cannot be invoked:
    Halt immediately with error
    Exit 1
    Message: "[ERROR] Cannot invoke execution verifier"
```

**Precondition 3: Exit Code Handling**
```
The controller must be prepared to receive:
- Exit 0: Intent is approved
- Exit 1: Intent is not approved (for any reason)
- Other: Treat as error (exit 1)

No interpretation of stderr output.
Only exit code matters.
```

**Precondition 4: No Tool Registry Loaded**
```
The controller must NOT:
- Import ARGO tool definitions
- Load tool registry
- Access tool list
- Read tool parameters
- Know what tools exist

This is intentional separation.
ARGO loads tools only after controller says "eligible."
```

**Precondition 5: No Intent Text Available**
```
The controller must NOT:
- Reconstruct original intent from hash
- Assume what intent text was
- Infer intent meaning
- Have access to pending.jsonl

Intent text is none of the controller's business.
That comes later, from ARGO, after eligibility is confirmed.
```

**Precondition 6: Human Has Already Confirmed**
```
The controller assumes:
- Voice was captured by intent_queue.py
- Human reviewed in intent_review.py
- Human typed "yes"
- Human obtained approved intent_id and hash

The controller does not re-confirm. It verifies state.
```

### Hard Stop Conditions

If any precondition fails, the controller stops immediately with error:

- ❌ intent_execute.py missing or uncallable
- ❌ Exit code is not 0 or 1
- ❌ UUID format invalid
- ❌ Hash format invalid
- ❌ Execution controller itself fails for any reason

**Never proceed if preconditions unmet. Never default to execution.**

---

## 4. Verification Flow

**Exact step-by-step process (no branching beyond this):**

```
Step 1: Receive Inputs
        UUID from human
        Hash from human
        Validate both formats exist

Step 2: Invoke intent_execute.py
        Call: python intent_execute.py <uuid> <hash>
        Wait for completion
        Capture exit code

Step 3: Check Exit Code
        If exit code == 0:
            Intent is APPROVED
            Proceed to Step 4
        If exit code == 1:
            Intent is NOT APPROVED
            Stop immediately
            Output: [ERROR] Approval verification failed
            Exit 1
        If exit code is anything else:
            Unexpected error
            Stop immediately
            Output: [ERROR] Verification tool error
            Exit 1

Step 4: Check Execution Eligibility
        Load executed.jsonl (or equivalent replay-detection record)
        Check if this UUID is in executed list
        If yes:
            Already executed
            Stop immediately
            Output: [ERROR] Intent already executed
            Exit 1
        If no:
            Not yet executed
            Proceed to Step 5

Step 5: Signal Eligibility to ARGO
        Output: [OK] Intent eligible for execution
        Exit 0
        ARGO may now proceed
```

**Critical constraint:** No branching logic beyond the above steps. Each step flows to the next or stops. No loops, no retries, no fallbacks.

---

## 5. Single-Execution Semantics (Critical)

This is the first time replay prevention is handled system-wide.

### Where "Already Executed" State is Tracked

**Location**: A new append-only file separate from approval queue

**File**: `I:\argo\intent_queue\executed.jsonl`

**Format**: JSON Lines, same structure as approved.jsonl

**Content per line**: 
```json
{
  "id": "uuid-of-executed-intent",
  "timestamp": "when-it-was-executed-iso",
  "hash": "sha256-for-verification"
}
```

**Why separate file?**
- approved.jsonl tracks human decisions (approval)
- executed.jsonl tracks system state (execution)
- Keeps concerns separate
- Both append-only
- Both immutable

### How Replay is Detected

**Detection algorithm:**

1. After approval verification succeeds (exit 0 from intent_execute.py)
2. Controller loads executed.jsonl
3. Scans for matching UUID
4. If found: Intent already executed once
5. If not found: Intent eligible for first execution

**Critical**: No check of "how recently" executed. No "execute once per N hours" logic. Once executed = done. Period.

### What Happens on Replay Attempt

**Scenario:**
```
Intent approved: b2831d73-2708-4f50-944b-7b54f11bfbb4
First execution: Ran successfully at 2026-01-15T12:00:00Z
Second attempt: Human accidentally runs ARGO again with same intent

Expected behavior:
```

**Behavior:**
```
Step 1: intent_execute.py called
        Returns exit 0 (still approved)

Step 2: executed.jsonl checked
        UUID found in file
        Timestamp: 2026-01-15T12:00:00Z

Step 3: Stop immediately
        Output: [ERROR] Intent already executed at 2026-01-15T12:00:00Z
        Exit 1
        No action taken
```

**Human's job**: See the error, understand intent was already executed, move on or review intent history.

### State Mutation Constraints

**The controller:**
- Reads executed.jsonl (no modification)
- After ARGO confirms execution, **ARGO** writes to executed.jsonl (not controller)

**Why ARGO writes, not controller?**
- Controller verifies eligibility only
- ARGO is responsible for actual execution
- ARGO knows if execution succeeded or failed
- ARGO appends to executed.jsonl **only if execution succeeds**

**Sequence:**
```
1. Controller says "eligible" (exit 0)
2. ARGO executes tool
3. ARGO checks result
4. If success: ARGO appends to executed.jsonl
5. If failure: executed.jsonl NOT modified
6. Next attempt: Controller sees no record, allows retry
```

---

## 6. Execution Eligibility Boundary

### What Conditions Allow ARGO to Proceed

✓ Intent UUID is in approved.jsonl  
✓ Hash matches stored hash exactly  
✓ intent_execute.py returns exit 0  
✓ UUID is NOT in executed.jsonl  
✓ No ambiguity in state  

**All conditions must be true. Any one failing blocks execution.**

### What Conditions Deny Execution (Even if Approved)

✗ UUID in approved.jsonl but hash mismatch → Stop  
✗ UUID in approved.jsonl but also in executed.jsonl → Stop  
✗ approved.jsonl is missing → Stop  
✗ executed.jsonl is corrupted → Stop  
✗ intent_execute.py fails or is missing → Stop  
✗ State is ambiguous in any way → Stop  

### Examples

**Example 1: Approved, Not Executed**
```
approved.jsonl: contains {id: uuid-A, hash: hash-X}
executed.jsonl: does not contain uuid-A
intent_execute.py: returns 0

Result: ELIGIBLE
Action: ARGO proceeds
```

**Example 2: Approved, Already Executed**
```
approved.jsonl: contains {id: uuid-A, hash: hash-X}
executed.jsonl: contains {id: uuid-A, timestamp: 2026-01-15T12:00:00Z}
intent_execute.py: returns 0

Result: DENIED (already executed)
Action: Stop, error message to human
```

**Example 3: Hash Mismatch**
```
approved.jsonl: contains {id: uuid-B, hash: hash-Y}
intent_execute.py: provided hash doesn't match hash-Y
intent_execute.py: returns 1

Result: DENIED (approval failed)
Action: Stop, error message to human
```

**Example 4: Ambiguous State (Corrupted executed.jsonl)**
```
executed.jsonl: contains partial JSON on last line
Controller attempts to parse: fails
Result: DENIED
Action: Stop, error message to human
Prevention: intent_queue layer must guarantee atomic writes
```

---

## 7. What the Controller Must Never Do

**Explicit prohibitions:**

❌ Execute tools or commands  
❌ Load ARGO tool registry  
❌ Import ARGO tool modules  
❌ Parse or reconstruct intent text  
❌ Infer what the intent means  
❌ Make safety decisions ("is this safe to run?")  
❌ Auto-retry verification failures  
❌ Auto-schedule execution  
❌ Silence or hide errors  
❌ Modify approved.jsonl  
❌ Modify executed.jsonl directly (only ARGO does after actual execution)  
❌ Check system state or configuration  
❌ Invoke background processes  
❌ Create persistent state beyond executed.jsonl  
❌ Make assumptions about intent based on hash  
❌ Time-gate execution ("don't run until 5 minutes have passed")  
❌ Attempt to recover from errors gracefully  

**Why these are forbidden:**

If the controller needs to do any of these, the boundary between "eligibility" and "execution" is wrong, and the architecture should be reconsidered.

---

## 8. Human Role

### What Humans Must Still Do Manually

1. **Trigger ARGO**: Human types command or clicks button to start execution
2. **Provide intent**: Human gives UUID and hash from intent_review.py output
3. **See failures**: Human reads error messages
4. **Decide next action**: Human decides whether to retry, investigate, or abandon
5. **Verify results**: Human checks that action actually happened
6. **Investigate corruption**: If executed.jsonl or approved.jsonl is corrupted, human fixes

### What System Must Never Do

❌ Auto-execute without human triggering  
❌ Auto-retry after failures  
❌ Auto-approve intents  
❌ Auto-schedule execution  
❌ Hide errors  
❌ Decide that "probably the human meant yes"  
❌ Silently skip already-executed intents  
❌ Proceed without human consent at every step  

**Every decision point is visible. Every failure is loud. Every action is human-triggered.**

---

## 9. Non-Goals

**This controller is NOT about:**

❌ **Performance tuning**: Disk IO for eligibility checks is acceptable. No caching, no pre-loading.

**Why not:** One-shot system. File reads are fast enough. Caching introduces state management complexity.

❌ **Parallel execution**: Only one intent at a time. No batching.

**Why not:** Serial execution is simpler, safer, more auditable. If parallelism is needed, add a scheduler layer later.

❌ **Convenience features**: No auto-recovery, smart defaults, or friendly UX.

**Why not:** Friction is intentional. Convenience is where bugs hide.

❌ **Background processing**: No daemons, no scheduled re-checks.

**Why not:** Everything is human-triggered, one-shot. Keeps the system transparent and controllable.

❌ **"Smart" decisions**: The controller doesn't decide, it verifies.

**Why not:** Decisions belong to humans. System enforces rules, doesn't make choices.

❌ **Optimization for latency**: No shortcuts, no clever caching.

**Why not:** Latency doesn't matter. A 100ms file read is not a bottleneck in a one-shot system.

❌ **Error recovery**: If something fails, it stays failed until human intervenes.

**Why not:** Silent recovery is worse than loud failure. Let humans see and understand what broke.

❌ **Future extensibility**: No hooks for "we might need this later."

**Why not:** Over-designing for hypothetical futures creates hidden complexity. Add features when needed, not before.

---

## 10. Summary

**The ARGO Execution Controller is a stateless verifier that decides whether execution may happen, not what happens.**

It answers one question: "Can ARGO run this intent now?" by checking two things: (1) Is it approved? and (2) Has it already run?

If both checks pass, it signals approval. ARGO then decides what tool to run and how to run it.

The controller is not responsible for executing tools, understanding intent, or making safety decisions. Those are ARGO's problems (next layer). The controller's only job is eligibility verification.

---

## Absolute Rules for ARGO Execution Controller

### Rule 1: Verification, Not Execution

The controller verifies eligibility. It does not execute.

The moment the controller needs to know what the intent says, the boundary is wrong.

### Rule 2: Separate Concerns

- **Approval** (was this intent approved by human?) → intent_execute.py answers
- **Eligibility** (can we run this now?) → controller answers
- **Execution** (run tool X) → ARGO answers

Each layer answers exactly one question.

### Rule 3: Append-Only State

Both approved.jsonl and executed.jsonl are append-only. No deletion, no modification.

This preserves audit trail forever.

### Rule 4: Fail Closed

If anything is ambiguous, unreadable, or corrupt, stop immediately with error.

Better to deny legitimate execution than silently proceed with corrupted state.

### Rule 5: No Side Effects from Verification

Reading approved.jsonl and executed.jsonl is the only side effect.

The controller does not:
- Modify files
- Create logs
- Send network requests
- Update any state
- Invoke any tools

### Rule 6: Human Always Sees Decisions

Every decision (eligible, not eligible, error) is printed clearly to human.

No silent path through the controller.

### Rule 7: Single Responsibility

The controller does one thing: determine if execution is eligible.

If it starts doing two things, the architecture is leaking.

### Rule 8: Synchronous, Blocking, One-Shot

The controller does not:
- Return to background processing
- Loop or retry
- Queue for later
- Check back periodically

Human triggers → controller decides → output sent to ARGO.

---

## Integration Points (Not Yet Implemented)

### Where Controller Connects to ARGO

**Future flow** (not today):

```
Human: triggers ARGO with approved intent
       Provides: intent_id and hash

ARGO calls Controller:
  "Is this intent eligible?"

Controller does:
  1. Verify approval (call intent_execute.py)
  2. Check execution history
  3. Return: eligible (exit 0) or not (exit 1)

ARGO receives result:
  If exit 0: controller returns "[OK] Intent eligible"
  If exit 1: controller returns "[ERROR]" + reason

ARGO acts on result:
  If eligible: select tool and execute
  If not: print error, stop, await human decision
```

### Separation of Concerns

| Layer | Responsible For |
|-------|---|
| Intent Queue | Record intent, delay action |
| Intent Review | Human approval gate |
| Intent Execute | Verify approval against approved.jsonl |
| **Execution Controller** | **Verify eligibility (not already executed)** |
| ARGO Tools | Actually execute commands |

Each layer answers exactly one question. No overlap.

---

## Summary: Controller's Job

**Input**: Approved intent UUID and hash  
**Question**: Can this intent run now?  
**Checks**: (1) Is it approved? (2) Has it already run?  
**Output**: Eligible (exit 0) or Not (exit 1)  
**Next**: ARGO decides what to do if eligible  

**That's it.** No execution. No tool selection. No intent parsing. Pure eligibility verification.
