# Executable Intent Layer (v1.2.0)

**Status:** ✅ Complete  
**Date:** January 17, 2026  
**Schema:** 1.2.0

---

## Overview

The **Executable Intent Layer** transforms validated user intents into explicit, concrete plans. Plans describe **what will happen and how it will happen** — but do NOT execute.

This is the planning layer: deterministic, auditable, and always requiring user confirmation before execution (v1.3.0).

### Architecture

```
IntentArtifact (v1.1.0)
    "user wants to write a file"
              ↓
        (Intent validates)
              ↓
ExecutableIntent Engine
    "Here's the 3-step plan..."
              ↓
    Plan Summary + Confirmation Gate
              ↓
    (User reviews and confirms)
              ↓
Execution Layer (v1.3.0) - NOT YET IMPLEMENTED
    "Running step 1, 2, 3..."
```

---

## Core Concepts

### ExecutableStep

Each step is a single, atomic operation.

```python
ExecutableStep(
    step_id=1,
    action_type=ActionType.WRITE,
    target="document.txt",
    operation="create_file",
    parameters={"path": "document.txt", "content": "..."},
    safety_level=SafetyLevel.CAUTIOUS,
    rollback_capability=RollbackCapability.FULL,
    rollback_procedure="Delete file and restore from backup",
    required_confirmations=["confirm_overwrite"],
)
```

**Key Properties:**
- `action_type` — What kind of action (READ, WRITE, DELETE, CREATE, etc.)
- `safety_level` — Risk assessment (SAFE, CAUTIOUS, RISKY, CRITICAL)
- `rollback_capability` — Can we undo this? (FULL, PARTIAL, NONE)
- `rollback_procedure` — Exact steps to undo (if reversible)
- `required_confirmations` — User must approve before execution

### ExecutablePlan

A complete plan with multiple steps, risk analysis, and rollback info.

```python
plan = ExecutablePlan(
    plan_id="plan_abc123...",
    intent_id="intent_def456...",
    intent_text="Write my document to ~/Documents/report.txt"
)

# Add steps
plan.add_step(step1)
plan.add_step(step2)
plan.add_step(step3)

# Plan automatically tracks:
# - Total steps
# - Highest risk level across all steps
# - Irreversible actions
# - Total confirmations needed
# - Overall rollback capability
```

---

## Safety Model

### Risk Levels

| Level | Meaning | Examples |
|-------|---------|----------|
| **SAFE** | No state change, read-only | Loading, querying, reading files |
| **CAUTIOUS** | State change, fully reversible | Writing (with backup), creating (can delete) |
| **RISKY** | State change, partially reversible | Modifying specific parts of files |
| **CRITICAL** | Irreversible state change | Permanent deletion, destructive operations |

### Rollback Capability

| Capability | Meaning |
|------------|---------|
| **FULL** | Complete undo possible (backup exists, can restore) |
| **PARTIAL** | Can mitigate but not fully revert (deleted file, but recovery possible) |
| **NONE** | No rollback possible (permanent deletion) |

### Confirmation Gates

Every operation with risk >= CAUTIOUS requires explicit user confirmation:

```python
# Safety mechanism: No blind execution
step = ExecutableStep(
    ...
    required_confirmations=["confirm_overwrite"],
)

# Before execution (v1.3.0):
# "File test.txt exists. Confirm overwrite? [yes/no]"
```

---

## Plan Derivation Rules

The `PlanDeriver` engine has rules for translating each intent verb into executable steps.

### Rule: WRITE

**Input:** Intent to write/create a file  
**Output:** 3-step plan

```
1. CHECK_EXISTS test.txt
   → Determine if file already exists

2. BACKUP_EXISTING test.txt → test.txt.backup
   → If file exists, create backup first

3. WRITE_FILE test.txt
   → Write new content (requires confirmation if overwriting)
```

**Safety:** CAUTIOUS (reversible via backup)

### Rule: OPEN

**Input:** Intent to open a file or application  
**Output:** 2-step plan

```
1. LOCATE document.pdf
   → Find in current dir, recent, or system paths

2. OPEN document.pdf
   → Launch file/application
```

**Safety:** SAFE (no state change)

### Rule: SAVE

**Input:** Intent to save document to a location  
**Output:** 2-step plan

```
1. CHECK_PATH /home/user/documents
   → Verify target location is writable

2. SAVE_DOCUMENT /home/user/documents/file.txt
   → Save with confirmation on destination
```

**Safety:** CAUTIOUS (state change, partially reversible)

### Rule: SHOW

**Input:** Intent to display content  
**Output:** 2-step plan

```
1. LOAD dashboard
   → Prepare content

2. DISPLAY primary_screen
   → Show on screen (can be dismissed)
```

**Safety:** SAFE (display only, no state change)

### Rule: SEARCH

**Input:** Intent to find files or content  
**Output:** 3-step plan

```
1. PREPARE_QUERY query="python files"
   → Build search expression

2. SEARCH file_system
   → Execute search (read-only)

3. SHOW_RESULTS
   → Display results (max 20)
```

**Safety:** SAFE (query-only, no modification)

---

## Usage Example

### Scenario: User says "Write my report to ~/Documents/report.txt"

```python
from wrapper.executable_intent import ExecutableIntentEngine

# Initialize engine
engine = ExecutableIntentEngine()

# Suppose IntentArtifact parsed this as:
intent = {
    "verb": "write",
    "object": "~/Documents/report.txt",
    "content": "Q1 2026 Financial Report...",
}

# Derive the plan
plan = engine.plan_from_intent(
    intent_id="intent_f7d9c2e1",
    intent_text="Write my report to ~/Documents/report.txt",
    parsed_intent=intent
)

# Display plan to user
print(plan.summary())
```

**Output:**

```
Plan: plan_a1b2c3d4
From Intent: intent_f7d9c2e1
User Said: "Write my report to ~/Documents/report.txt"

Steps: 3
Confirmations Needed: 1
Risk Level: CAUTIOUS
Fully Reversible: Yes

Plan Steps:
  1. CHECK_EXISTS ~/Documents/report.txt
     Action Type: query
     Safety: SAFE
  2. BACKUP_EXISTING ~/Documents/report.txt → ~/Documents/report.txt.backup
     Action Type: create
     Safety: CAUTIOUS
     Constraints: Only if file exists
  3. WRITE_FILE ~/Documents/report.txt
     Action Type: write
     Safety: CAUTIOUS
     Requires: confirm_overwrite
```

**User sees this plan and decides:**
- "Yes, proceed" → Stored as awaiting_confirmation, ready for v1.3.0
- "No, stop" → Plan discarded, nothing happens
- "Modify the plan" → Plan stored for manual editing

---

## Critical Safety Features

### 1. No Execution Occurs in v1.2.0

```python
# This is guaranteed by design:
plan = engine.plan_from_intent(...)  # ← Plan created
# ↓
# No files are created, modified, or deleted
# No applications are opened
# No system state changes
# Everything is just DESCRIBED in the plan
```

### 2. All State-Changing Operations Have Rollback Plans

```python
# Every WRITE/CREATE/DELETE step includes rollback:
step.rollback_capability = RollbackCapability.FULL
step.rollback_procedure = "Restore from backup"

# So even if execution fails, we know how to fix it
```

### 3. Confirmation Gates Are Explicit

```python
# Before any risky operation:
if step.required_confirmations:
    # User MUST explicitly approve

# v1.3.0 will enforce this:
# "Confirm: Overwrite existing file? [yes/no]"
```

### 4. Auditability

Every plan is logged with full context:

```
2026-01-17 18:15:42 [INFO] Deriving plan for intent f7d9c2e1: write
2026-01-17 18:15:42 [INFO] Plan derived: plan_a1b2c3d4 with 3 steps
```

Complete plan data is stored (for session) as JSON:

```json
{
  "plan_id": "plan_a1b2c3d4",
  "intent_id": "intent_f7d9c2e1",
  "intent_text": "Write my report to ~/Documents/report.txt",
  "steps": [
    {
      "step_id": 1,
      "action_type": "query",
      "target": "~/Documents/report.txt",
      "operation": "check_exists",
      ...
    }
  ],
  "highest_risk_level": "cautious",
  "has_irreversible_actions": false,
  "can_fully_rollback": true,
  "status": "derived"
}
```

---

## Determinism

**Same intent → Same plan structure every time**

This is critical. The planning layer must be deterministic so:
1. User can learn what plans look like
2. Plans are predictable and trustworthy
3. Testing and validation is possible
4. No "magical" behavior surprises

Example:
```python
# Same intent, same plan
for i in range(5):
    plan = engine.plan_from_intent(
        intent_id=f"intent_{i}",
        intent_text="Write test.txt",
        parsed_intent={"verb": "write", "object": "test.txt", "content": "test"}
    )
    # All 5 plans have identical step sequences
```

---

## Integration with v1.1.0 (Intent Layer)

### Flow

```
v1.1.0: IntentArtifact
    Parses user utterance
    Validates grammar
    Preserves ambiguity
    Returns: {"verb": "write", "object": "file.txt", ...}
              ↓
v1.2.0: ExecutableIntent
    Translates intent to plan
    Analyzes risks
    Defines rollback procedures
    Returns: ExecutablePlan with steps, confirmations, safety metadata
              ↓
v1.3.0: Execution (Future)
    Reviews user confirmation
    Executes steps 1-by-1
    Monitors state changes
    Handles failures + rollback
```

### No Dependency on v1.0.0 (Transcription)

v1.2.0 accepts intents from ANY source:
- Direct text input
- Transcribed audio (v1.0.0)
- System messages
- APIs

Same planning engine applies to all.

---

## Session-Only Storage

Like v1.0.0 and v1.1.0, plans are **session-only**:

```python
engine = ExecutableIntentEngine()
plan1 = engine.plan_from_intent(...)  # Stored in memory
plan2 = engine.plan_from_intent(...)  # Stored in memory

# At session end: All plans cleared
# Next session: Clean start
```

Logging is permanent (`runtime/logs/executable_plans.log`), but plan objects are ephemeral.

---

## Known Limitations

### v1.2.0 Does NOT Support

- Branching/conditional plans (if X then Y)
- Plan composition (combining multiple intents)
- Natural language rollback descriptions
- Plan optimization (finding most efficient sequence)
- Cost estimation (time, resource usage)

These are planned for future versions.

### v1.2.0 Does NOT Execute

- NO file operations
- NO application launches
- NO system commands
- NO network requests
- NO device control

All execution is deferred to v1.3.0.

---

## Testing

**26/26 tests passing**

Coverage includes:
- Step creation and serialization
- Plan metadata management
- Risk level tracking
- Rollback capability detection
- All 5 derivation rules
- Unknown intent fallback
- Plan storage and retrieval
- Session-only semantics
- Determinism validation
- Safety features
- Audit logging
- Critical: No execution verification

Run tests:
```bash
python -m pytest test_executable_intent.py -v
```

---

## Code Structure

### Core Classes

| Class | Purpose |
|-------|---------|
| `ExecutableStep` | Single atomic operation with safety metadata |
| `ExecutablePlan` | Complete plan from intent with risk analysis |
| `PlanDeriver` | Translates intents to plans using derivation rules |
| `ExecutablePlanStorage` | Session-only in-memory storage with logging |
| `ExecutableIntentEngine` | Main interface (user-facing) |

### Enums

| Enum | Values |
|------|--------|
| `ActionType` | READ, WRITE, DELETE, CREATE, MODIFY, CONTROL, QUERY, DISPLAY |
| `SafetyLevel` | SAFE, CAUTIOUS, RISKY, CRITICAL |
| `RollbackCapability` | FULL, PARTIAL, NONE |

### Files

- `wrapper/executable_intent.py` — Core implementation (700+ lines)
- `test_executable_intent.py` — Test suite (26 tests)
- `docs/intent/executable_intent.md` — This documentation

---

## Next Steps (v1.3.0: Execution Engine)

Once v1.2.0 plans are confirmed by the user, v1.3.0 will:

1. **Execute steps 1-by-1** in order
2. **Monitor state changes** (before/after snapshots)
3. **Handle failures** (logs, rollback triggers)
4. **Report results** (what changed, what didn't)
5. **Offer rollback** (if user wants to undo)

The execution engine will use the rollback procedures defined in v1.2.0 plans.

---

## Design Philosophy

### Why Plan Before Execute?

**Separation of concerns:**
- **Planning** (v1.2.0): Is this safe? What could go wrong? How do we undo?
- **Execution** (v1.3.0): Actually make the changes

**User control:**
- User can review plan before execution
- User can ask questions ("What's in the backup?", "Can I modify this?")
- User can say no without wasting resources

**Auditability:**
- Clear record of intent → plan → execution
- Traceable failure points
- Explainable behavior

### Why No Branching?

Complex conditional logic (if/else/while) is:
- Hard to predict
- Easy to misunderstand
- Risky without user oversight

v1.2.0 keeps plans **linear and simple**. Complex workflows are composed in v1.3.0 by chaining multiple confirmations.

---

## Maintenance

### Logs

Plans are logged to:
```
runtime/logs/executable_intent.log
runtime/logs/executable_plans.log  (detailed JSON)
```

### Adding New Derivation Rules

To support a new intent verb (e.g., "compose"):

1. Add method `_derive_compose_plan(self, plan, intent)`
2. Register in `_load_derivation_rules()`
3. Test with `test_executable_intent.py`
4. Document in this file

Example:
```python
def _derive_compose_plan(self, plan: ExecutablePlan, intent: Dict[str, Any]) -> None:
    """Plan: Compose multiple documents into one"""
    
    # Add steps...
    step1 = ExecutableStep(...)
    plan.add_step(step1)
    
    # Add more steps...
```

---

## Summary

**ExecutableIntent (v1.2.0):**
- ✅ Transforms intents into detailed plans
- ✅ Analyzes risks and rollback capability
- ✅ Deterministic: same intent → same plan
- ✅ Auditable: full logging of plans and reasoning
- ✅ Safe: no execution, just planning
- ✅ User-controlled: confirmation gates before action

**Ready for:**
- v1.3.0 Execution Engine integration
- End-user testing and feedback
- Additional derivation rules
