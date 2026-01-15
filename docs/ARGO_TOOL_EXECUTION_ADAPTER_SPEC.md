# ARGO Tool Execution Adapter Specification

**Document Type**: Design Specification (Not Implementation)  
**Status**: Design Phase - Tool Execution Boundary Definition  
**Date**: 2026-01-15  
**Purpose**: Define safe tool execution boundaries after eligibility is confirmed

---

## Purpose

**What the adapter enables:**

1. Receive approved intent UUID and hash
2. Confirm eligibility signal from argo_execution_controller.py
3. Load tool registry (read-only)
4. Select exactly one tool based on intent ID
5. Validate tool parameters
6. Execute that single tool
7. Record execution attempt
8. Signal success or failure to caller
9. Stop

**Core principle:**

**This adapter allows execution; it does not interpret intent.**

The adapter never decides what to do. The human decided when they approved the intent. The controller verified it's eligible. The adapter just runs it.

**What the adapter explicitly refuses to do:**

❌ Interpret intent meaning from intent text  
❌ Decide which tool to use (it's already decided via tool registry)  
❌ Chain multiple tools  
❌ Fallback to alternative tools  
❌ Retry on failure  
❌ Modify approved intents  
❌ Create new intents  
❌ Auto-approve anything  
❌ Assume what user probably meant  
❌ Optimize for convenience  
❌ Execute without controller signal  
❌ Log raw intent content  
❌ Make safety decisions  
❌ Schedule anything  
❌ Run in background  

---

## Inputs

### Input 1: Approved Intent UUID

**Format**: Standard UUID (36 characters, lowercase, hyphens)  
**Source**: Command-line argument or caller  
**Validation**: Must match valid UUID format or fail immediately  
**Example**: `b2831d73-2708-4f50-944b-7b54f11bfbb4`  
**Used for**: Looking up tool definition in registry

### Input 2: Intent Hash (SHA256)

**Format**: Hex string, 64 characters  
**Source**: Command-line argument or caller  
**Validation**: Must match controller's hash or fail immediately  
**Purpose**: Verify intent has not been modified since approval  
**Note**: Hash is for verification only, never used to reconstruct intent

### Input 3: Eligibility Signal

**Source**: argo_execution_controller.py exit code  
**Valid values**: Exit 0 = eligible, Exit 1 = not eligible  
**Precondition**: Controller must have returned exit 0 before adapter is invoked  
**Guarantee**: Adapter only runs if controller explicitly approved

### Invocation Characteristics

- **Synchronous**: Blocking, caller waits for result
- **Human-triggered**: Never automatic, never background
- **Single execution**: One run per invocation, no retries

---

## Preconditions (Hard Failures)

**Before any execution, all of these must be true:**

### Check 1: Controller Approval

```
If argo_execution_controller.py exit code != 0:
    Adapter does not run
    Print "[ERROR] Execution not eligible"
    Exit 1
```

**Why**: Controller is the only source of eligibility.

### Check 2: Tool Registry Loaded

```
If tool registry cannot be loaded:
    Print "[ERROR] Tool registry unavailable"
    Exit 1

If tool registry is writable (not read-only):
    Print "[ERROR] Tool registry must be read-only"
    Exit 1
```

**Why**: Registry is source of truth. Must not be modified during execution.

### Check 3: Intent UUID in Registry

```
If intent_id not found in tool registry:
    Print "[ERROR] Intent not in tool registry"
    Exit 1
```

**Why**: Tool selection is already decided. Adapter only looks up, never guesses.

### Check 4: Exactly One Tool Selected

```
If registry entry for intent_id maps to zero tools:
    Print "[ERROR] No tool defined for this intent"
    Exit 1

If registry entry for intent_id maps to multiple tools:
    Print "[ERROR] Multiple tools defined (ambiguous)"
    Exit 1

If registry entry for intent_id maps to exactly one tool:
    Continue
```

**Why**: No chaining, no fallbacks, no "try-one-then-another" logic.

### Check 5: Tool Arguments Validated

```
Load tool definition:
    - Tool name (string)
    - Tool executable path
    - Tool parameters (if any)
    - Parameter types and constraints

Validate all parameters:
    - Required parameters present
    - Parameter types correct
    - Parameter values within constraints
    - No dangerous/suspicious values

If validation fails:
    Print "[ERROR] Tool arguments invalid: <reason>"
    Exit 1
```

**Why**: Catch configuration errors before execution.

### Any Precondition Failure

```
On any precondition failure:
    - Print error message immediately
    - Do not attempt recovery
    - Do not retry
    - Exit 1
    - Stop
```

---

## Tool Selection Rules (Critical)

### Rule 1: One Intent → One Tool → One Execution

**Principle**: Single path, no branching.

```
approved_intent_uuid → [tool_registry lookup] → tool_definition → execute_once → stop
```

No alternate paths. No fallback tools. No "if-tool-fails-try-another."

### Rule 2: Tool is Already Decided

The human decided when they approved the intent.

The tool registry maps intent UUID → tool.

The adapter does not decide. It only looks up and executes.

### Rule 3: No Chaining

One tool executes. It completes (success or failure). Adapter stops.

Never:
- ❌ Run tool A, then tool B
- ❌ Run tool A, wait for result, then decide whether to run tool B
- ❌ Queue multiple tools
- ❌ Batch tools

### Rule 4: No Fallbacks

If selected tool fails, adapter fails. Period.

Never:
- ❌ "Tool A failed, try tool B"
- ❌ "Tool A returned error code 127, try alternate version"
- ❌ "Tool A didn't respond, retry with different args"

Failure is failure. Stop.

### Rule 5: No Retries

Tool runs once. If it fails, human investigates.

Never:
- ❌ Retry on network timeout
- ❌ Retry on exit code != 0
- ❌ Exponential backoff
- ❌ "Try up to 3 times"

One shot. No retries. No recovery.

### Rule 6: Ambiguity → Deny

If there's any doubt about which tool to run, or whether to run it, fail closed.

Examples:
- ❌ Intent UUID ambiguous → deny
- ❌ Multiple tools in registry for one intent → deny
- ❌ Tool definition incomplete → deny
- ❌ Parameters invalid → deny
- ❌ Tool executable not found → deny

All cases: Exit 1, print error, stop.

---

## Execution Boundary

### Where Execution Starts

**Input boundary**: Eligibility confirmed, tool selected, parameters validated.

Preconditions:
- argo_execution_controller.py returned exit 0
- Tool registry loaded
- Intent UUID found in registry
- Exactly one tool mapped
- Tool parameters valid
- All checks passed

Execution layer begins here.

### Where It Ends

**Output boundary**: Execution result reported, execution recorded.

Adapter returns:
- Exit code 0: Execution succeeded (tool returned 0)
- Exit code 1: Execution failed (tool returned non-zero, or adapter error)

Then adapter stops. Nothing else happens.

### What Success Looks Like

```
Tool selected: [tool_name]
Tool executed: [command_line]
Tool exit code: 0
Output captured: [stdout/stderr as appropriate]
Execution recorded: executed.jsonl
Caller notified: "[OK] Execution completed"
Stop
```

### What Failure Looks Like

```
Tool selected: [tool_name]
Tool executed: [command_line]
Tool exit code: 1 (non-zero)
Error output: [stderr]
Execution recorded: executed.jsonl (with failure flag)
Caller notified: "[ERROR] Execution failed: <reason>"
Stop
```

Or:

```
Precondition failed: [Check 3]
Reason: Tool registry incomplete
Execution NOT attempted
Execution NOT recorded
Caller notified: "[ERROR] Cannot execute"
Stop
```

### Atomic Execution Only

**Principle**: Tool runs completely or not at all.

Never:
- ❌ Partial execution (tool runs 50%, adapter stopped)
- ❌ Partial state (some side effects happened, some didn't)
- ❌ Retry in middle of execution (tool already started side effects)

If execution starts, it completes to tool's end. Then adapter records result and stops.

---

## Output Handling

### What stdout/stderr is Allowed

**Tool stdout**: Captured, shown to human if tool succeeds  
**Tool stderr**: Captured, shown to human if tool fails  
**Adapter stdout**: Short status messages only

Valid adapter outputs:
```
[OK] Execution completed
[ERROR] Tool not found
[ERROR] Precondition failed: <reason>
[ERROR] Tool returned non-zero exit code
```

Invalid adapter outputs:
- ❌ "[HINT] Did you mean..."
- ❌ "[INFO] This tool is slow, might take a while"
- ❌ "[WARNING] Tool returned code 1, retrying..."
- ❌ Debugging information
- ❌ Internal state details
- ❌ Stack traces (unless tool generated them)

### How Results/Errors are Shown to Human

**On success**:
```
[OK] Execution completed: <tool_name>
Tool output:
<captured stdout>
Execution ID: <uuid>
```

**On failure**:
```
[ERROR] Execution failed: <tool_name>
Exit code: <code>
Error output:
<captured stderr>
Execution ID: <uuid>
```

**On precondition failure**:
```
[ERROR] Cannot execute: <reason>
No execution attempted.
```

### No Silent Failures

Every execution attempt must result in clear human-visible message:
- ❌ Never silent success
- ❌ Never swallowed errors
- ❌ Never "assume it worked"
- ❌ Never "we'll tell them later"

Immediate, clear, human-readable. Always.

### No Retries

If tool fails, output goes to human. Human decides next step.

Adapter never retries. Never.

---

## Post-Execution Recording

### What Gets Written to executed.jsonl

**File location**: I:\argo\intent_queue\executed.jsonl  
**Format**: JSON Lines (one object per line, append-only)  
**Timing**: Recorded immediately after execution attempt (success or failure)

**Each line contains**:
```json
{
  "id": "approved_intent_uuid",
  "timestamp": "2026-01-15T14:32:45.123Z",
  "tool": "tool_name_that_was_executed",
  "exit_code": 0,
  "outcome": "success"
}
```

Or on failure:
```json
{
  "id": "approved_intent_uuid",
  "timestamp": "2026-01-15T14:32:46.456Z",
  "tool": "tool_name_that_was_executed",
  "exit_code": 127,
  "outcome": "failure"
}
```

**Fields**:
- `id`: UUID of the approved intent (for replay detection)
- `timestamp`: ISO-8601 formatted time of execution
- `tool`: Name of the tool that was executed
- `exit_code`: Return code from the tool (0 = success, non-zero = failure)
- `outcome`: "success" or "failure" (human-readable)

**What is NOT recorded**:
- ❌ Raw intent text
- ❌ Tool output/stderr
- ❌ Detailed error messages (captured separately)
- ❌ User identity
- ❌ System state
- ❌ Full command-line arguments

### When Recording Happens

**Timing**: After execution completes (success or failure)

```
1. Preconditions check
2. Tool selection
3. Tool execution
4. Capture exit code
5. [WRITE TO executed.jsonl] ← Here
6. Report result to human
7. Stop
```

Recording happens even if tool failed.

Recording happens even if output was confusing.

Recording always happens (assuming adapter can write to file).

### If Recording Fails

**Scenario**: Adapter tried to write to executed.jsonl but file write failed

**Behavior**:
```
[ERROR] Execution recording failed
Execution may have happened, may not have.
Status unknown.
Treat entire execution as failed.
Exit 1
```

**Why**: If we can't record execution, we can't prevent replay. Fail closed.

---

## What the Adapter Must Never Do

### Never Execute Tools

Wait, that sounds contradictory. Clarification:

Adapter orchestrates exactly one tool execution. But it never:
- ❌ Decide which tool to execute (tool registry decides)
- ❌ Decide whether to execute (controller decides)
- ❌ Decide what the tool does (tool decides)
- ❌ Decide when to stop (tool completion decides)

Adapter is the executor, not the decider.

### Never Interpret Intent

Never attempt to understand what the human meant.

Never:
- ❌ Parse intent text
- ❌ Infer intent from patterns
- ❌ Guess what user probably wanted
- ❌ Reconstruct intent from hash
- ❌ Assume intent meaning

Tool registry already decided this. Adapter just looks it up.

### Never Modify Approvals

Never touch approved.jsonl or pending.jsonl.

Never:
- ❌ Delete approved intent
- ❌ Mark intent as "already processed"
- ❌ Rename intent
- ❌ Modify timestamp
- ❌ Archive intent

Execution record goes to executed.jsonl only. Approval files untouched.

### Never Retry

Never attempt recovery or retry logic.

Never:
- ❌ "Tool failed, retry once"
- ❌ "Timeout, try again with longer timeout"
- ❌ "Network error, retry later"
- ❌ "Tool hung, send kill signal and retry"

One execution. Success or failure. Stop.

### Never Chain Tools

Never execute multiple tools in sequence.

Never:
- ❌ Run tool A, then check output, then run tool B
- ❌ "If tool A fails, try tool B"
- ❌ Queue of tools to execute in order
- ❌ Conditional tool selection

One tool. One execution. Stop.

### Never Make Safety Decisions

Never decide if tool is "safe to run."

Never:
- ❌ "This tool looks dangerous, blocking"
- ❌ "This tool needs elevated privileges, denying"
- ❌ "This tool hasn't been audited, refusing"

The controller already verified approval. That's safety decision enough. Adapter executes.

### Never Schedule Anything

Never defer, delay, batch, or queue execution.

Never:
- ❌ "Run this at 3pm instead"
- ❌ "Batch these 5 intents together"
- ❌ "Schedule for later"
- ❌ "Run in background"

Synchronous. Now. Blocking. Or not at all.

### Never Execute Without Eligibility

Never bypass the controller.

Never:
- ❌ Execute intent that controller said no to
- ❌ "Trust me, I know this is safe"
- ❌ "Just run it this once"
- ❌ "Skip the controller check"

Controller returns exit 0, or adapter doesn't run. No exceptions.

---

## Human Role

### What the Human Sees Before Execution

```
[PRE-EXECUTION]
Approved intent UUID: b2831d73-2708-4f50-944b-7b54f11bfbb4
Tool to execute: create_backup
Tool executable: /path/to/backup_tool.sh
Tool parameters: [--target /home/user/important]
Eligibility: CONFIRMED (controller exit 0)
Registry check: PASSED
Parameter validation: PASSED

Ready to execute. Proceed? (y/n)
```

Human sees:
- What tool will run
- What parameters it will receive
- Confirmation that it's approved and eligible
- Chance to cancel

Human must explicitly confirm before execution starts.

### What the Human Sees After Execution

**On success**:
```
[OK] Execution completed: create_backup
Execution ID: b2831d73-2708-4f50-944b-7b54f11bfbb4
Timestamp: 2026-01-15T14:32:45.123Z
Tool output:
  Backup created: /backup/2026-01-15_143245.tar.gz
  Size: 2.3 GB
  Time: 12 seconds
Status: Execution recorded in executed.jsonl
```

Human sees:
- Confirmation it completed
- What the tool produced
- How it was recorded

### On Failure**:
```
[ERROR] Execution failed: create_backup
Execution ID: b2831d73-2708-4f50-944b-7b54f11bfbb4
Timestamp: 2026-01-15T14:32:46.456Z
Exit code: 1
Error output:
  create_backup: cannot access /home/user/important
  Permission denied
Status: Execution recorded in executed.jsonl as failure
```

Human sees:
- What failed
- Why it failed
- That failure was recorded

### What the Human Must Do on Failure

1. **Understand the error**: Read the output
2. **Investigate**: Check logs, verify tool, check parameters
3. **Decide next step**: Retry manually, fix issue, or accept failure
4. **Never automatic retry**: Adapter will not retry for them

Human is responsible for deciding what happens next.

### What the Human Must Never Do

❌ Try to bypass the controller  
❌ Modify execution records  
❌ Delete approvals  
❌ "Trust me, just execute it"  
❌ Expect automatic retry  

Every execution is intentional and recorded. Human is responsible for their approvals.

---

## Non-Goals

**This adapter spec is NOT about:**

### ❌ Performance Tuning

**Why not**: Single synchronous execution is not a bottleneck. Optimization is premature.

Current behavior: Tool runs at its own pace. That's enough.

Future: If execution becomes bottleneck (extremely unlikely for one-shot system), add parallelism as separate layer.

### ❌ Tool Chaining

**Why not**: One intent → one tool. Chaining is separate problem.

If we need tool A then tool B, that's a new intent.

Current: Single tool only. Multi-step processes are human responsibility (approve intent A, then approve intent B).

Future: If chaining becomes common pattern, design as separate layer with its own controller/approval.

### ❌ Autonomy

**Why not**: Friction is intentional. Humans must consciously approve.

Current: Synchronous, human-triggered, blocking.

Future: If background execution becomes required, design as scheduler layer, not here.

### ❌ Background Execution

**Why not**: One-shot, synchronous, blocking is simpler and safer.

Current: Tool runs now, caller waits, result reported.

Future: If async becomes necessary, add queue layer, not here.

### ❌ "Helpful" Behavior

**Why not**: Helpful often means "making assumptions about what user wants."

Current: Adapter executes exactly what was approved, nothing more.

Examples we explicitly reject:
- ❌ "You're low on disk space, should I clean up?"
- ❌ "This command seems risky, let me block it"
- ❌ "I notice you usually run X after Y, should I add it?"
- ❌ "This tool is slow, I'll timeout and retry"

Helpful = complexity. Complexity = mistakes. Mistakes = danger. We don't do helpful.

---

## Summary

The ARGO Tool Execution Adapter executes exactly one approved action under strict constraints and stops. It receives eligibility confirmation from the controller, selects a single tool from the registry, validates parameters, runs the tool synchronously, records the execution attempt (success or failure), reports results to the human, and terminates. No chaining, no fallbacks, no retries, no interpretation of intent, no autonomous decisions. It is an executor, not a decider. Execution happens or fails cleanly, recorded atomically, reported clearly. The human triggered it, the human approves the tool, the human decides what happens next on failure. The adapter's single job is to run one tool safely and stop.

---

## Absolute Rules for Tool Execution

### Rule 1: One Intent → One Tool

Exactly one tool executes per invocation. Never multiple, never chained, never conditional.

### Rule 2: Controller or Failure

Execution requires controller exit 0. Otherwise, fail immediately.

### Rule 3: Registry is Source of Truth

Tool selection comes from registry lookup. Registry is read-only. Adapter never decides which tool.

### Rule 4: Ambiguity Denies

Any doubt about intent, tool, parameters, or eligibility causes immediate failure (exit 1).

### Rule 5: No Retries

One execution. Success or failure. Stop.

### Rule 6: Atomic Recording

If execution starts, result is recorded to executed.jsonl. If recording fails, entire execution treated as failed.

### Rule 7: No Side Effects on Denial

If precondition fails, tool does not run. No partial execution. No state changes.

### Rule 8: Human Verification

Human must confirm execution before it starts. Confirmation is not automatic.

### Rule 9: Clear Reporting

All results (success or failure) reported immediately to human in clear, complete language.

### Rule 10: Fail Closed

When in doubt, fail. Better to deny one legitimate execution than to execute one illegitimate action.

---

## Integration Points (Not Yet Implemented)

### Where Tool Execution Connects to Larger System

**Future flow** (not today):

```
Human: approves intent in intent_review.py
        Gets: intent_id and hash

ARGO Execution Controller called:
  python argo_execution_controller.py <intent_id> <hash>
  Returns: exit 0 (eligible) or exit 1 (not eligible)

If exit 0:
  ARGO Tool Execution Adapter called:
    python argo_tool_execution_adapter.py <intent_id> <hash>
    Executes: the single tool from registry
    Records: execution attempt in executed.jsonl
    Returns: exit 0 (tool succeeded) or exit 1 (tool failed)

Human sees: success or failure message
```

**Separation of concerns**:

| Layer | Responsibility |
|-------|---|
| Intent Queue | Record intent, delay action |
| Intent Review | Human approval gate |
| Execution Controller | Verify approval + prevent replay |
| **Tool Execution Adapter** | **Execute one tool, record result** |

Each layer has one job. Adapter's job: "Run this tool and record what happened."

---

## Summary: What This Spec Defines

This specification defines the **tool execution boundary** without implementing anything.

**It answers:**
- What enables tool execution? (Controller confirmation)
- Which tool to execute? (Registry lookup)
- When to fail? (Any ambiguity, any precondition failure)
- What happens after execution? (Result recording, human notification)
- What is forever forbidden? (Chaining, retries, interpretation, autonomy)
- What is the human's role? (Confirmation, decision-making on failure)

**It does NOT:**
- Write code
- Define tool registry format (that's separate layer)
- Handle concurrent executions (not supported)
- Schedule future execution (not supported)
- Optimize for speed (not a goal)
- Add "helpful" features (explicitly forbidden)

**Next steps** (if requested):
1. Implement tool execution adapter based on this spec
2. Define tool registry schema
3. Create sample tool registry
4. Test adapter with simple tool
5. Integrate with controller (full pipeline)

**For now**: Spec only. Commit the doc. Stop.
