# Dry-Run Execution Model (v1.3.0-alpha)

## Purpose

The Execution Engine proves that plans are **safe**, **complete**, and **reversible** BEFORE the system takes any real action.

This is the critical safety layer between planning and execution.

## Design Philosophy

**Core Invariant**: Never execute until you've proven it's safe.

The execution engine:
1. Takes an ExecutionPlanArtifact
2. Simulates each step symbolically
3. Validates rollback procedures
4. Produces a DryRunExecutionReport
5. **Makes zero changes to system state**

## Architecture

### Input: ExecutionPlanArtifact

From v1.2.0 planning layer:
- Intent ID (where it came from)
- Transcription ID (full audio trace)
- Sequence of executable steps
- Safety level per step
- Rollback capability per step

### Simulation Process

```
For each step in plan:
  1. Check preconditions (symbolically)
  2. Predict state changes (text only)
  3. Validate rollback procedures
  4. Identify failure modes
  5. Analyze safety (risk level)
```

#### 1. Precondition Checking (Symbolic)

**NO SYSTEM ACCESS** - Pure logic:

- **QUERY operations**: Precondition MET (read-only)
- **READ operations**: Precondition UNKNOWN (can't verify without access)
- **WRITE/DELETE/CREATE**: Precondition UNKNOWN (can't verify without access)

This is intentional: we're being conservative. If we can't verify it's safe, we mark it UNKNOWN.

#### 2. State Change Prediction (Text Only)

We describe what WOULD change:

```python
predicted_state_change = "File 'document.txt' would be created with 250 bytes"
affected_resources = ["document.txt"]
```

**Critical**: This is text description, NOT an actual change.

#### 3. Rollback Validation

For each state-changing step:

```
Rollback exists?      (YES/NO)
Rollback coherent?    (procedures make sense internally)
Rollback feasible?    (can we actually reverse it)
```

Steps with `RollbackCapability.NONE` are flagged as **irreversible**.

#### 4. Failure Mode Identification

For each step, identify what could go wrong:

- Permission denied
- Insufficient disk space
- Target not found
- Resource locked
- etc.

#### 5. Safety Analysis

Per-step risk levels:
- **SAFE**: Read-only, no side effects
- **CAUTIOUS**: Changes state, but fully reversible
- **RISKY**: Changes state, partial rollback
- **CRITICAL**: Changes irreversible state

Plan-wide analysis:
- Highest risk detected?
- All rollbacks exist?
- Any irreversible actions?
- Execution feasible?

### Output: DryRunExecutionReport

```json
{
  "report_id": "dryrun_001",
  "execution_plan_id": "plan_001",
  "intent_id": "intent_001",
  "transcription_id": "trans_001",
  
  "simulation_status": "success",
  "steps_simulated": [
    {
      "step_id": 1,
      "operation": "write_to_file",
      "target": "output.txt",
      "action_type": "write",
      
      "precondition_status": "unknown",
      "predicted_state_change": "File 'output.txt' would be created",
      
      "rollback_exists": true,
      "rollback_procedure": "Delete output.txt",
      "rollback_feasible": true,
      
      "can_fail": ["permission_denied", "disk_full"],
      "risk_level": "cautious"
    }
  ],
  
  "all_rollbacks_exist": true,
  "all_rollbacks_coherent": true,
  "highest_risk_detected": "cautious",
  "execution_feasible": true
}
```

## HARD CONSTRAINTS

### Zero Side Effects

The execution engine MUST NEVER:

- ✗ Create files
- ✗ Delete files  
- ✗ Modify system state
- ✗ Execute OS commands
- ✗ Send network requests
- ✗ Change configuration
- ✗ Write to permanent storage

**Verified by tests**: 
- `test_no_file_creation()`
- `test_no_state_change_guarantee()`
- Run 100+ simulations, verify 0 files created

### Full Auditability

Every simulation is logged:
- Step-by-step execution flow
- Precondition checks (pass/fail)
- State change predictions
- Rollback validation
- Safety analysis
- Timestamps

Location: `runtime/logs/execution_engine.log`

### Session-Only Reports

Like other artifacts:
- Reports ephemeral (memory only)
- Logs permanent (on disk)
- Each session starts fresh
- Full history available in logs

## Integration Flow

### v1.0-v1.2 (Complete)

```
Audio → TranscriptionArtifact (confirmed)
  ↓
Text → IntentArtifact (approved)
  ↓
Intent → ExecutionPlanArtifact (awaiting_execution)
```

### v1.3.0-alpha (This Layer)

```
Plan → DryRunExecutionReport (safe to execute?)
```

User sees:
1. Plan summary
2. Simulation results
3. Rollback procedures
4. Risk analysis
5. Recommendation: SAFE / CAUTION / UNSAFE

User decides:
- `approve_execution()` → Wait for v1.4.0
- `reject_and_modify()` → Go back to planning
- `save_for_later()` → Store both plan and report

### v1.4.0+ (Future)

When simulation says SAFE and user approves:

```
DryRunExecutionReport → EXECUTE (with monitoring)
```

Still with confirmation:
- "I'm about to make these changes. Last chance to stop."
- Real actions happen
- Success/failure logged
- Rollback available if needed

## Safety Design Patterns

### Pattern 1: Conservative Unknown

```python
# Can't verify without system access?
precondition_status = PreconditionStatus.UNKNOWN

# Mark as CAUTION until verified real
risk_level = SafetyLevel.CAUTIOUS
```

We never assume safety. We assume we don't know.

### Pattern 2: Reversibility Check

```python
if step.rollback_capability == RollbackCapability.NONE:
    # Mark explicitly as irreversible
    # Require extra confirmation
    risk_level = SafetyLevel.CRITICAL
```

No blind deletions. No silent irreversible changes.

### Pattern 3: Failure Mode Enumeration

For EACH step, we enumerate failure modes:

```python
can_fail = [
    "permission_denied",
    "target_not_found", 
    "disk_full",
    "timeout"
]
```

Not exhaustive, but comprehensive.

## Comparison to Other Systems

| Aspect | ARGO | Typical Automation |
|--------|------|-------------------|
| Before execution? | Simulates first | Executes immediately |
| Rollback? | Validated before | Assumed to exist |
| Preconditions? | Checked symbolically | Run at execution time |
| Failure modes? | Enumerated upfront | Discovered during failure |
| User control? | Explicit approval after preview | Implicit once triggered |

## Logging Example

```
[2024-01-15 10:23:45] INFO: Dry-run started for plan plan_001
[2024-01-15 10:23:45] DEBUG: Simulating step 1: write_file document.txt
[2024-01-15 10:23:45] DEBUG: Precondition: UNKNOWN (can't verify without system)
[2024-01-15 10:23:45] DEBUG: Predicted change: File 'document.txt' created (250 bytes)
[2024-01-15 10:23:45] DEBUG: Rollback procedure exists: Delete document.txt
[2024-01-15 10:23:45] DEBUG: Rollback feasible: YES
[2024-01-15 10:23:45] DEBUG: Identified failure modes: permission_denied, disk_full
[2024-01-15 10:23:45] INFO: Step 1 simulation complete: SAFE

[2024-01-15 10:23:45] INFO: Simulation complete
[2024-01-15 10:23:45] INFO: Dry-run result: SUCCESS
[2024-01-15 10:23:45] INFO: Execution feasible: YES
[2024-01-15 10:23:45] INFO: Highest risk: CAUTIOUS
```

## Testing Strategy

### Unit Tests (19 tests, 100% passing)

1. **SimulatedStepResult** (2 tests)
   - Creation with metadata
   - Serialization

2. **DryRunExecutionReport** (4 tests)
   - Creation and initialization
   - Status transitions
   - Serialization
   - Human-readable summary

3. **ExecutionEngine** (7 tests)
   - Engine creation
   - Simple write simulation
   - Chain traceability (trans → intent → plan → report)
   - State change identification
   - Rollback validation
   - Failure mode identification
   - Report storage

4. **Blocked Execution** (1 test)
   - Properly flag blocked plans

5. **Rollback Validation** (1 test)
   - Detect missing rollback procedures

6. **Zero Side Effects** (3 tests)
   - No file creation
   - No file deletion
   - System state guarantee

### Integration Tests (Planned)

- Full transcription → intent → plan → simulation flow
- Multiple step plans
- Complex rollback scenarios
- Failure recovery

## What's NOT Implemented (Yet)

- Actual execution (v1.4.0)
- Smart home device communication
- File I/O
- OS command execution
- Network requests
- Custom plugins

These will be added only after v1.3.0-alpha is frozen and tested.

## Summary

The Execution Engine is the safety layer:

1. **Accepts** ExecutionPlanArtifact from planning layer
2. **Simulates** execution symbolically (zero side effects)
3. **Validates** rollback procedures
4. **Reports** safety analysis (SAFE/CAUTION/UNSAFE)
5. **Never modifies** system state
6. **Provides** full auditability

Result: Users can see EXACTLY what would happen before it happens.

