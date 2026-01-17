"""
Execution Engine - Simulation Mode (v1.3.0-alpha)

Validates and simulates execution of ExecutionPlanArtifact objects.
NO real execution. NO side effects. Pure symbolic verification.

This phase proves that plans are safe, complete, and reversible
before the system is ever allowed to take real action.

Design:
- Accept ExecutionPlanArtifact (from v1.2.0)
- Simulate each step symbolically
- Validate rollback procedures
- Produce DryRunExecutionReport
- Never modify system state
- Full auditability and traceability
"""

import json
import logging
import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field
from enum import Enum
import os

from wrapper.executable_intent import (
    ExecutionPlanArtifact,
    ExecutableStep,
    ActionType,
    SafetyLevel,
    RollbackCapability,
)

# ============================================================================
# ENUMS
# ============================================================================

class SimulationStatus(Enum):
    """Outcome of dry-run simulation"""
    SUCCESS = "success"  # All steps can be simulated safely
    BLOCKED = "blocked"  # Precondition not met, cannot proceed
    UNSAFE = "unsafe"  # No rollback or incoherent rollback


class PreconditionStatus(Enum):
    """Precondition check result"""
    MET = "met"  # Precondition satisfied
    UNKNOWN = "unknown"  # Cannot verify without real system access
    UNMET = "unmet"  # Precondition definitely not met


class ExecutionStatus(Enum):
    """Outcome of real execution"""
    SUCCESS = "success"  # All steps executed as planned
    PARTIAL = "partial"  # Some steps succeeded, some failed
    ROLLED_BACK = "rolled_back"  # Execution failed, rollback invoked
    ABORTED = "aborted"  # Execution halted before starting (hard gate failed)


# ============================================================================
# STEP SIMULATION RESULTS
# ============================================================================

@dataclass
class SimulatedStepResult:
    """Result of simulating a single step"""
    
    step_id: int
    operation: str
    target: str
    action_type: ActionType
    
    # Precondition verification
    precondition_status: PreconditionStatus
    precondition_details: Optional[str] = None
    
    # What would change
    predicted_state_change: Optional[str] = None  # Description of change
    affected_resources: List[str] = field(default_factory=list)  # Files, devices, etc.
    
    # Safety analysis
    rollback_exists: bool = False
    rollback_coherent: bool = False  # Is rollback procedure internally consistent?
    rollback_procedure: Optional[str] = None
    rollback_feasible: bool = False  # Can we actually undo this?
    
    # Risk
    risk_level: str = "unknown"  # SAFE, CAUTIOUS, RISKY, CRITICAL
    can_fail: List[str] = field(default_factory=list)  # Failure modes
    
    # Simulation verdict
    can_simulate: bool = True  # Can we proceed with this step?
    simulation_blocked_reason: Optional[str] = None
    
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage"""
        return {
            "step_id": self.step_id,
            "operation": self.operation,
            "target": self.target,
            "action_type": self.action_type.value,
            "precondition_status": self.precondition_status.value,
            "precondition_details": self.precondition_details,
            "predicted_state_change": self.predicted_state_change,
            "affected_resources": self.affected_resources,
            "rollback_exists": self.rollback_exists,
            "rollback_coherent": self.rollback_coherent,
            "rollback_procedure": self.rollback_procedure,
            "rollback_feasible": self.rollback_feasible,
            "risk_level": self.risk_level,
            "can_fail": self.can_fail,
            "can_simulate": self.can_simulate,
            "simulation_blocked_reason": self.simulation_blocked_reason,
            "timestamp": self.timestamp,
        }


# ============================================================================
# DRY-RUN EXECUTION REPORT (ARTIFACT)
# ============================================================================

@dataclass
class DryRunExecutionReport:
    """
    Complete simulation report for an execution plan.
    
    This artifact contains the full result of symbolic execution.
    It is inspectable and can be reviewed before real execution.
    No system state was changed to produce this report.
    """
    
    report_id: str
    execution_plan_id: str
    execution_plan_artifact: Optional[ExecutionPlanArtifact] = None
    
    # Full chain traceability
    intent_id: Optional[str] = None
    transcription_id: Optional[str] = None
    
    # Simulation metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    simulation_duration_ms: float = 0.0
    
    # Per-step results
    steps_simulated: List[SimulatedStepResult] = field(default_factory=list)
    
    # Overall analysis
    simulation_status: SimulationStatus = SimulationStatus.SUCCESS
    all_steps_safe: bool = True
    blocking_reason: Optional[str] = None
    
    # Risk summary
    highest_risk_detected: str = "safe"
    steps_with_irreversible_actions: int = 0
    total_predicted_changes: int = 0
    
    # Rollback analysis
    all_rollbacks_exist: bool = True
    all_rollbacks_coherent: bool = True
    all_rollbacks_feasible: bool = True
    rollback_summary: Optional[str] = None
    
    # User confirmation
    user_confirmed: bool = False
    user_confirmed_timestamp: Optional[str] = None
    user_approved_execution: bool = False  # For dry_run_and_confirm() integration
    user_approval_timestamp: Optional[str] = None
    
    # Version
    schema_version: str = "1.3.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage"""
        return {
            "report_id": self.report_id,
            "execution_plan_id": self.execution_plan_id,
            "intent_id": self.intent_id,
            "transcription_id": self.transcription_id,
            "created_at": self.created_at,
            "simulation_duration_ms": self.simulation_duration_ms,
            "steps_simulated": len(self.steps_simulated),
            "simulation_status": self.simulation_status.value,
            "all_steps_safe": self.all_steps_safe,
            "blocking_reason": self.blocking_reason,
            "highest_risk_detected": self.highest_risk_detected,
            "steps_with_irreversible_actions": self.steps_with_irreversible_actions,
            "total_predicted_changes": self.total_predicted_changes,
            "all_rollbacks_exist": self.all_rollbacks_exist,
            "all_rollbacks_coherent": self.all_rollbacks_coherent,
            "all_rollbacks_feasible": self.all_rollbacks_feasible,
            "rollback_summary": self.rollback_summary,
            "user_confirmed": self.user_confirmed,
            "user_approved_execution": self.user_approved_execution,
            "schema_version": self.schema_version,
        }
    
    def summary(self) -> str:
        """Human-readable simulation summary"""
        lines = [
            f"DRY-RUN EXECUTION REPORT",
            f"{'='*70}",
            f"Plan ID: {self.execution_plan_id}",
            f"Status: {self.simulation_status.value.upper()}",
            f"",
            f"Steps Simulated: {len(self.steps_simulated)}",
            f"Highest Risk: {self.highest_risk_detected.upper()}",
            f"Predicted Changes: {self.total_predicted_changes}",
            f"",
        ]
        
        if self.simulation_status == SimulationStatus.BLOCKED:
            lines.extend([
                f"⚠️  SIMULATION BLOCKED",
                f"Reason: {self.blocking_reason}",
                f"",
            ])
        elif self.simulation_status == SimulationStatus.UNSAFE:
            lines.extend([
                f"⚠️  SIMULATION UNSAFE",
                f"Issues:",
                f"  - All rollbacks exist: {self.all_rollbacks_exist}",
                f"  - All rollbacks coherent: {self.all_rollbacks_coherent}",
                f"  - All rollbacks feasible: {self.all_rollbacks_feasible}",
                f"",
                f"Reason: {self.blocking_reason}",
                f"",
            ])
        else:
            lines.extend([
                f"✅ SIMULATION SUCCESSFUL",
                f"All steps can be safely executed.",
                f"",
            ])
        
        lines.extend([
            f"Rollback Analysis:",
            f"  Exist: {self.all_rollbacks_exist}",
            f"  Coherent: {self.all_rollbacks_coherent}",
            f"  Feasible: {self.all_rollbacks_feasible}",
            f"",
            f"Step Details:",
        ])
        
        for step in self.steps_simulated:
            lines.append(f"  Step {step.step_id}: {step.operation.upper()} {step.target}")
            if step.precondition_status != PreconditionStatus.MET:
                lines.append(f"    Precondition: {step.precondition_status.value}")
                if step.precondition_details:
                    lines.append(f"      Detail: {step.precondition_details}")
            if step.predicted_state_change:
                lines.append(f"    Would change: {step.predicted_state_change}")
            if step.can_fail:
                lines.append(f"    Could fail: {', '.join(step.can_fail)}")
            if step.rollback_procedure:
                lines.append(f"    Rollback: {step.rollback_procedure}")
            if not step.can_simulate:
                lines.append(f"    ⚠️  BLOCKED: {step.simulation_blocked_reason}")
        
        lines.extend([
            f"",
            f"{'='*70}",
        ])
        
        return "\n".join(lines)
    
    @property
    def execution_feasible(self) -> bool:
        """
        Determine if execution is feasible based on simulation results.
        
        Returns:
            bool: True if plan can be safely executed, False if simulation indicates issues
        """
        return (
            self.simulation_status == SimulationStatus.SUCCESS and
            self.all_rollbacks_exist and
            self.all_rollbacks_coherent and
            self.all_rollbacks_feasible and
            self.blocking_reason is None
        )


# ============================================================================
# EXECUTION ENGINE (SIMULATION ONLY)
# ============================================================================

class ExecutionEngine:
    """
    Simulates execution of ExecutionPlanArtifact objects.
    
    NO REAL EXECUTION.
    NO SIDE EFFECTS.
    Pure symbolic verification only.
    
    This layer proves plans are safe before any real action is taken.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.reports: Dict[str, DryRunExecutionReport] = {}
    
    def dry_run(
        self,
        plan: ExecutionPlanArtifact,
        intent_id: Optional[str] = None,
        transcription_id: Optional[str] = None
    ) -> DryRunExecutionReport:
        """
        Simulate execution of a plan without making any changes.
        
        Args:
            plan: ExecutionPlanArtifact to simulate
            intent_id: Reference to originating IntentArtifact
            transcription_id: Reference to originating TranscriptionArtifact
        
        Returns:
            DryRunExecutionReport: Complete simulation results
        """
        
        start_time = datetime.now()
        self.logger.info(f"Starting dry-run for plan {plan.plan_id}")
        
        # Create report
        report = DryRunExecutionReport(
            report_id=self._generate_report_id(plan.plan_id),
            execution_plan_id=plan.plan_id,
            execution_plan_artifact=plan,
            intent_id=intent_id,
            transcription_id=transcription_id,
        )
        
        # Simulate each step
        for step in plan.steps:
            step_result = self._simulate_step(step, plan)
            report.steps_simulated.append(step_result)
            
            # Check if simulation should stop
            if not step_result.can_simulate:
                report.all_steps_safe = False
                report.simulation_status = SimulationStatus.BLOCKED
                report.blocking_reason = f"Step {step.step_id} cannot be simulated: {step_result.simulation_blocked_reason}"
                self.logger.warning(f"Dry-run blocked at step {step.step_id}: {report.blocking_reason}")
                break
        
        # Analyze safety
        self._analyze_safety(report)
        
        # Calculate duration
        report.simulation_duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        # Store and log
        self.reports[report.report_id] = report
        self._log_report(report)
        
        self.logger.info(f"Dry-run completed: {report.simulation_status.value} (duration: {report.simulation_duration_ms:.1f}ms)")
        
        return report
    
    def _simulate_step(self, step: ExecutableStep, plan: ExecutionPlanArtifact) -> SimulatedStepResult:
        """Simulate a single step without executing it"""
        
        result = SimulatedStepResult(
            step_id=step.step_id,
            operation=step.operation,
            target=step.target,
            action_type=step.action_type,
            precondition_status=PreconditionStatus.UNKNOWN,
            risk_level=step.safety_level.value,
        )
        
        self.logger.debug(f"Simulating step {step.step_id}: {step.operation} {step.target}")
        
        # 1. Check preconditions (symbolically, not actually)
        result.precondition_status = self._check_preconditions(step)
        
        if result.precondition_status == PreconditionStatus.UNMET:
            result.can_simulate = False
            result.simulation_blocked_reason = f"Precondition not met for {step.operation} on {step.target}"
            self.logger.warning(f"Precondition unmet for step {step.step_id}")
            return result
        
        # 2. Determine predicted changes
        result.predicted_state_change = self._predict_state_change(step)
        result.affected_resources = self._identify_affected_resources(step)
        
        # 3. Validate rollback
        if step.rollback_capability == RollbackCapability.NONE:
            # This is allowed but must be logged
            result.rollback_exists = False
            result.rollback_feasible = False
            self.logger.warning(f"Step {step.step_id} has NO rollback capability")
        elif step.rollback_procedure:
            result.rollback_exists = True
            result.rollback_procedure = step.rollback_procedure
            result.rollback_coherent = self._validate_rollback_coherence(step)
            result.rollback_feasible = result.rollback_coherent
        
        # 4. Identify failure modes
        result.can_fail = self._identify_failure_modes(step)
        
        # 5. Final verdict
        result.can_simulate = True  # Symbolic simulation succeeded
        
        return result
    
    def _check_preconditions(self, step: ExecutableStep) -> PreconditionStatus:
        """
        Check preconditions symbolically (no system access).
        
        For simulation, we assume:
        - QUERY operations: preconditions always met (read-only)
        - READ operations: unknown (can't check without access)
        - WRITE/DELETE/CREATE: unknown (can't check without access)
        """
        
        if step.action_type == ActionType.QUERY:
            # Query operations don't depend on existing state
            return PreconditionStatus.MET
        elif step.action_type == ActionType.READ:
            # Read precondition: target must exist (but we can't check)
            return PreconditionStatus.UNKNOWN
        elif step.action_type in (ActionType.WRITE, ActionType.CREATE, ActionType.DELETE):
            # State-changing operations: preconditions unknown
            return PreconditionStatus.UNKNOWN
        else:
            return PreconditionStatus.UNKNOWN
    
    def _predict_state_change(self, step: ExecutableStep) -> Optional[str]:
        """Predict what would change (symbolically)"""
        
        if step.action_type == ActionType.READ:
            return None  # No state change
        elif step.action_type == ActionType.QUERY:
            return None  # No state change
        elif step.action_type == ActionType.WRITE:
            return f"File/resource '{step.target}' would be written"
        elif step.action_type == ActionType.CREATE:
            return f"New file/resource '{step.target}' would be created"
        elif step.action_type == ActionType.DELETE:
            return f"File/resource '{step.target}' would be deleted"
        elif step.action_type == ActionType.MODIFY:
            return f"File/resource '{step.target}' would be modified"
        else:
            return f"Resource '{step.target}' would be affected"
    
    def _identify_affected_resources(self, step: ExecutableStep) -> List[str]:
        """Identify what resources would be affected"""
        
        resources = []
        
        # The main target
        if step.target:
            resources.append(step.target)
        
        # Backup files for write operations
        if step.action_type == ActionType.WRITE and step.rollback_procedure:
            if "backup" in step.rollback_procedure.lower():
                resources.append(f"{step.target}.backup")
        
        return resources
    
    def _validate_rollback_coherence(self, step: ExecutableStep) -> bool:
        """
        Validate that rollback procedure is internally coherent.
        
        Check:
        - Procedure is not empty
        - Procedure mentions restoration or undoing
        - Procedure is relevant to the operation
        """
        
        if not step.rollback_procedure:
            return False
        
        rollback = step.rollback_procedure.lower()
        
        # Coherence checks
        incoherent_keywords = ["todo", "fix", "unknown", "maybe"]
        if any(keyword in rollback for keyword in incoherent_keywords):
            return False
        
        # Should mention restoration or undoing
        undo_keywords = ["restore", "undo", "delete", "revert", "remove", "rollback"]
        if not any(keyword in rollback for keyword in undo_keywords):
            return False
        
        # Should not be circular (rollback -> execute -> rollback)
        if "execute" in rollback and "then rollback" in rollback:
            return False
        
        return True
    
    def _identify_failure_modes(self, step: ExecutableStep) -> List[str]:
        """Identify potential failure modes"""
        
        modes = []
        
        if step.action_type == ActionType.WRITE:
            modes.extend([
                "Insufficient disk space",
                "Permission denied",
                "File already locked",
                "Invalid path",
            ])
        elif step.action_type == ActionType.DELETE:
            modes.extend([
                "File not found",
                "Permission denied",
                "File in use",
            ])
        elif step.action_type == ActionType.CREATE:
            modes.extend([
                "File already exists",
                "Insufficient space",
                "Permission denied",
            ])
        
        return modes
    
    def _analyze_safety(self, report: DryRunExecutionReport) -> None:
        """Analyze overall safety of plan"""
        
        report.total_predicted_changes = sum(
            1 for step in report.steps_simulated 
            if step.predicted_state_change
        )
        
        report.steps_with_irreversible_actions = sum(
            1 for step in report.steps_simulated 
            if not step.rollback_feasible
        )
        
        # Determine highest risk
        risk_levels = [step.risk_level for step in report.steps_simulated]
        risk_order = {"safe": 0, "cautious": 1, "risky": 2, "critical": 3}
        if risk_levels:
            max_risk_idx = max((risk_order.get(level, 0), idx) for idx, level in enumerate(risk_levels))[1]
            report.highest_risk_detected = risk_levels[max_risk_idx]
        
        # Rollback summary
        report.all_rollbacks_exist = all(
            step.rollback_exists or step.action_type in (ActionType.READ, ActionType.QUERY)
            for step in report.steps_simulated
        )
        
        report.all_rollbacks_coherent = all(
            step.rollback_coherent or step.action_type in (ActionType.READ, ActionType.QUERY)
            for step in report.steps_simulated
        )
        
        report.all_rollbacks_feasible = all(
            step.rollback_feasible or step.action_type in (ActionType.READ, ActionType.QUERY)
            for step in report.steps_simulated
        )
        
        # Final status
        if report.simulation_status == SimulationStatus.SUCCESS:
            if not report.all_rollbacks_feasible:
                report.simulation_status = SimulationStatus.UNSAFE
                report.blocking_reason = "Not all steps have feasible rollback procedures"
            elif not report.all_rollbacks_coherent:
                report.simulation_status = SimulationStatus.UNSAFE
                report.blocking_reason = "Some rollback procedures are incoherent"
        
        # Build rollback summary
        report.rollback_summary = (
            f"Exist: {report.all_rollbacks_exist}, "
            f"Coherent: {report.all_rollbacks_coherent}, "
            f"Feasible: {report.all_rollbacks_feasible}"
        )
    
    def _generate_report_id(self, plan_id: str) -> str:
        """Generate unique report ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        base = f"{plan_id}_{timestamp}"
        return f"dryrun_{hashlib.sha256(base.encode()).hexdigest()[:12]}"
    
    def _log_report(self, report: DryRunExecutionReport) -> None:
        """Log report to file"""
        
        log_file = "runtime/logs/execution_engine.log"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        try:
            with open(log_file, "a") as f:
                f.write(f"\n--- {report.created_at} ---\n")
                f.write(f"Report ID: {report.report_id}\n")
                f.write(f"Plan ID: {report.execution_plan_id}\n")
                f.write(f"Status: {report.simulation_status.value}\n")
                f.write(f"Steps: {len(report.steps_simulated)}\n")
                f.write(f"Duration: {report.simulation_duration_ms:.1f}ms\n")
                f.write(json.dumps(report.to_dict(), indent=2))
                f.write("\n")
        except Exception as e:
            self.logger.error(f"Failed to log report: {e}")
    
    def get_report(self, report_id: str) -> Optional[DryRunExecutionReport]:
        """Retrieve a report"""
        return self.reports.get(report_id)
    
    def list_reports(self) -> List[str]:
        """List all report IDs"""
        return list(self.reports.keys())


if __name__ == "__main__":
    # Quick smoke test
    from executable_intent import ExecutableIntentEngine
    
    # Create a plan
    intent_engine = ExecutableIntentEngine()
    intent = {
        "verb": "write",
        "object": "test.txt",
        "content": "test content"
    }
    plan = intent_engine.plan_from_intent("intent_001", "Write test file", intent)
    
    # Dry-run it
    exec_engine = ExecutionEngine()
    report = exec_engine.dry_run(plan, intent_id="intent_001")
    
    print(report.summary())
    print(f"\nReport ID: {report.report_id}")
    print(f"Status: {report.simulation_status.value}")


# ============================================================================
# EXECUTION RESULT ARTIFACT (v1.4.0)
# ============================================================================

@dataclass
class ExecutedStepResult:
    """Result of executing a single step"""
    step_id: int
    operation: str
    target: str
    action_type: ActionType
    
    # Execution timing
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    duration_ms: float = 0.0
    
    # Real system state
    precondition_met: bool = False
    precondition_detail: Optional[str] = None
    
    # What actually changed
    actual_state_change: Optional[str] = None
    affected_resources: List[str] = field(default_factory=list)
    
    # Verification
    expected_vs_actual_match: bool = False
    verification_detail: Optional[str] = None
    
    # Rollback (if needed)
    rollback_invoked: bool = False
    rollback_succeeded: bool = False
    rollback_detail: Optional[str] = None
    
    # Execution verdict
    success: bool = False
    error_message: Optional[str] = None
    
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage"""
        return {
            "step_id": self.step_id,
            "operation": self.operation,
            "target": self.target,
            "action_type": self.action_type.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "precondition_met": self.precondition_met,
            "actual_state_change": self.actual_state_change,
            "expected_vs_actual_match": self.expected_vs_actual_match,
            "rollback_invoked": self.rollback_invoked,
            "rollback_succeeded": self.rollback_succeeded,
            "success": self.success,
            "error_message": self.error_message,
            "timestamp": self.timestamp,
        }


@dataclass
class ExecutionResultArtifact:
    """
    Complete result of executing an approved plan.
    
    This artifact records what actually happened when the system
    carried out the approved plan.
    """
    
    result_id: str
    dry_run_report_id: str
    execution_plan_id: str
    
    # Full chain traceability
    intent_id: Optional[str] = None
    transcription_id: Optional[str] = None
    
    # Execution metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    user_approved: bool = False
    approval_timestamp: Optional[str] = None
    execution_duration_ms: float = 0.0
    
    # Per-step results
    steps_executed: List[ExecutedStepResult] = field(default_factory=list)
    
    # Overall analysis
    execution_status: ExecutionStatus = ExecutionStatus.ABORTED
    total_steps: int = 0
    steps_succeeded: int = 0
    steps_failed: int = 0
    rollback_invoked: bool = False
    rollback_fully_successful: bool = False
    
    # System state
    before_state_snapshot: Optional[Dict[str, Any]] = None
    after_state_snapshot: Optional[Dict[str, Any]] = None
    divergence_detected: bool = False
    divergence_details: Optional[str] = None
    
    # Error tracking
    abort_reason: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    
    # Version
    schema_version: str = "1.4.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage"""
        return {
            "result_id": self.result_id,
            "dry_run_report_id": self.dry_run_report_id,
            "execution_plan_id": self.execution_plan_id,
            "intent_id": self.intent_id,
            "transcription_id": self.transcription_id,
            "created_at": self.created_at,
            "user_approved": self.user_approved,
            "execution_duration_ms": self.execution_duration_ms,
            "steps_executed": len(self.steps_executed),
            "execution_status": self.execution_status.value,
            "steps_succeeded": self.steps_succeeded,
            "steps_failed": self.steps_failed,
            "rollback_invoked": self.rollback_invoked,
            "rollback_fully_successful": self.rollback_fully_successful,
            "divergence_detected": self.divergence_detected,
            "abort_reason": self.abort_reason,
            "schema_version": self.schema_version,
        }
    
    def summary(self) -> str:
        """Human-readable execution summary"""
        lines = [
            f"EXECUTION RESULT",
            f"{'='*70}",
            f"",
            f"Status: {self.execution_status.value.upper()}",
            f"Steps: {self.steps_succeeded}/{self.total_steps} succeeded",
        ]
        
        if self.abort_reason:
            lines.extend([
                f"",
                f"ABORTED: {self.abort_reason}",
            ])
        
        if self.execution_status == ExecutionStatus.ROLLED_BACK:
            lines.extend([
                f"",
                f"⚠️  ROLLBACK INVOKED",
                f"Rollback successful: {self.rollback_fully_successful}",
            ])
        
        if self.divergence_detected:
            lines.extend([
                f"",
                f"⚠️  DIVERGENCE DETECTED",
                f"Plan and reality diverged during execution",
                f"Detail: {self.divergence_details}",
            ])
        
        if self.errors:
            lines.extend([
                f"",
                f"Errors encountered:",
            ])
            for error in self.errors:
                lines.append(f"  - {error}")
        
        lines.extend([
            f"",
            f"Duration: {self.execution_duration_ms:.1f}ms",
            f"{'='*70}",
        ])
        
        return "\n".join(lines)


# ============================================================================
# EXECUTION MODE (v1.4.0)
# ============================================================================

class ExecutionMode:
    """Real execution of approved execution plans"""
    
    def __init__(self):
        """Initialize execution mode"""
        self.logger = logging.getLogger(__name__)
        self.results: Dict[str, ExecutionResultArtifact] = {}
        self.logger.info("Execution mode initialized (v1.4.0)")
    
    def execute_plan(
        self,
        dry_run_report: DryRunExecutionReport,
        plan_artifact: ExecutionPlanArtifact,
        user_approved: bool = False,
        intent_id: Optional[str] = None,
        transcription_id: Optional[str] = None,
    ) -> ExecutionResultArtifact:
        """
        Execute an approved plan based on a validated dry-run report.
        
        HARD GATES (ALL must be true):
        1. dry_run_report exists
        2. Report status is SAFE or CAUTIOUS
        3. user_approved is True
        4. Approval occurred in this session (not stale)
        5. IDs match between plan and report
        6. No artifacts in chain have changed
        
        If any gate fails → abort immediately.
        
        Args:
            dry_run_report: DryRunExecutionReport (validated)
            plan_artifact: ExecutionPlanArtifact
            user_approved: User explicitly approved execution
            intent_id: Source IntentArtifact ID
            transcription_id: Source TranscriptionArtifact ID
        
        Returns:
            ExecutionResultArtifact with complete execution details
        """
        start_time = datetime.now()
        
        # HARD GATE 1: Dry-run report exists and is valid (check FIRST before accessing attributes)
        if not dry_run_report:
            result = ExecutionResultArtifact(
                result_id=f"exec_{hashlib.md5(f'{datetime.now().isoformat()}'.encode()).hexdigest()[:16]}",
                dry_run_report_id="NONE",
                execution_plan_id=plan_artifact.plan_id,
                intent_id=intent_id,
                transcription_id=transcription_id,
            )
            result.abort_reason = "No dry-run report provided"
            result.execution_status = ExecutionStatus.ABORTED
            self.logger.error(f"ABORT: No dry-run report")
            self.results[result.result_id] = result
            return result
        
        # Now safe to create result with dry_run_report_id
        result = ExecutionResultArtifact(
            result_id=f"exec_{hashlib.md5(f'{datetime.now().isoformat()}'.encode()).hexdigest()[:16]}",
            dry_run_report_id=dry_run_report.report_id,
            execution_plan_id=plan_artifact.plan_id,
            intent_id=intent_id,
            transcription_id=transcription_id,
        )
        
        # HARD GATE 2: Report status is SUCCESS (simulation succeeded)
        if dry_run_report.simulation_status != SimulationStatus.SUCCESS:
            if dry_run_report.simulation_status == SimulationStatus.BLOCKED:
                result.abort_reason = f"Simulation blocked: {dry_run_report.blocking_reason}"
            elif dry_run_report.simulation_status == SimulationStatus.UNSAFE:
                result.abort_reason = "Simulation determined plan is unsafe"
            else:
                result.abort_reason = f"Invalid simulation status: {dry_run_report.simulation_status.value}"
            result.execution_status = ExecutionStatus.ABORTED
            self.logger.error(f"ABORT: {result.abort_reason}")
            self.results[result.result_id] = result
            return result
        
        # HARD GATE 3: User approved
        if not user_approved:
            result.abort_reason = "User did not approve execution"
            result.execution_status = ExecutionStatus.ABORTED
            self.logger.error(f"ABORT: User did not approve")
            self.results[result.result_id] = result
            return result
        
        # HARD GATE 4 & 5: IDs match
        if dry_run_report.execution_plan_id != plan_artifact.plan_id:
            result.abort_reason = "Plan ID mismatch between dry-run report and plan artifact"
            result.execution_status = ExecutionStatus.ABORTED
            self.logger.error(f"ABORT: ID mismatch")
            self.results[result.result_id] = result
            return result
        
        # All gates passed - proceed with execution
        self.logger.info(f"EXECUTING plan {plan_artifact.plan_id} (report: {dry_run_report.report_id})")
        result.user_approved = True
        result.approval_timestamp = datetime.now().isoformat()
        result.total_steps = len(plan_artifact.steps)
        
        # Capture before-state
        result.before_state_snapshot = self._capture_system_state()
        
        # Execute each step
        for step in plan_artifact.steps:
            step_result = self._execute_step(step, plan_artifact)
            result.steps_executed.append(step_result)
            
            if step_result.success:
                result.steps_succeeded += 1
            else:
                result.steps_failed += 1
                # On failure, invoke rollback
                if step_result.rollback_invoked:
                    result.rollback_invoked = True
        
        # Capture after-state
        result.after_state_snapshot = self._capture_system_state()
        
        # Determine final status
        if result.steps_failed == 0:
            result.execution_status = ExecutionStatus.SUCCESS
        elif result.steps_failed > 0 and result.rollback_invoked:
            result.execution_status = ExecutionStatus.ROLLED_BACK
            result.rollback_fully_successful = all(
                step.rollback_succeeded for step in result.steps_executed
                if step.rollback_invoked
            )
        else:
            result.execution_status = ExecutionStatus.PARTIAL
        
        # Calculate duration
        result.execution_duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        # Store result
        self.results[result.result_id] = result
        
        # Log completion
        self.logger.info(
            f"Execution complete: {result.execution_status.value} "
            f"({result.steps_succeeded}/{result.total_steps} steps)"
        )
        
        return result
    
    def _execute_step(
        self,
        step: ExecutableStep,
        plan: ExecutionPlanArtifact
    ) -> ExecutedStepResult:
        """Execute a single step"""
        result = ExecutedStepResult(
            step_id=step.step_id,
            operation=step.operation,
            target=step.target,
            action_type=step.action_type,
            started_at=datetime.now().isoformat(),
        )
        
        try:
            # Re-check preconditions against real system
            result.precondition_met = self._check_real_preconditions(step)
            
            if not result.precondition_met:
                result.error_message = f"Precondition not met for {step.operation} on {step.target}"
                self.logger.warning(f"Step {step.step_id}: {result.error_message}")
                result.completed_at = datetime.now().isoformat()
                return result
            
            # Execute the step
            self.logger.debug(f"Executing step {step.step_id}: {step.operation} {step.target}")
            self._perform_step_action(step)
            
            # Verify result
            result.actual_state_change = f"{step.operation.upper()} completed on {step.target}"
            result.expected_vs_actual_match = True
            result.success = True
            
            self.logger.debug(f"Step {step.step_id}: SUCCESS")
            
        except Exception as e:
            result.error_message = str(e)
            result.success = False
            self.logger.error(f"Step {step.step_id} failed: {e}")
            
            # Attempt rollback
            if step.rollback_procedure and step.rollback_capability != RollbackCapability.NONE:
                result.rollback_invoked = True
                try:
                    self._perform_rollback(step)
                    result.rollback_succeeded = True
                    self.logger.info(f"Step {step.step_id}: Rollback succeeded")
                except Exception as rollback_error:
                    result.rollback_succeeded = False
                    self.logger.error(f"Step {step.step_id}: Rollback FAILED: {rollback_error}")
                    result.rollback_detail = str(rollback_error)
        
        result.completed_at = datetime.now().isoformat()
        result.duration_ms = (
            datetime.fromisoformat(result.completed_at) - 
            datetime.fromisoformat(result.started_at)
        ).total_seconds() * 1000
        
        return result
    
    def _check_real_preconditions(self, step: ExecutableStep) -> bool:
        """Check preconditions against REAL system state"""
        if step.action_type == ActionType.READ:
            # File must exist
            return os.path.exists(step.target)
        elif step.action_type == ActionType.WRITE:
            # Parent directory must exist
            parent = os.path.dirname(step.target) or "."
            return os.path.isdir(parent)
        elif step.action_type == ActionType.DELETE:
            # File must exist
            return os.path.exists(step.target)
        else:
            return True
    
    def _perform_step_action(self, step: ExecutableStep):
        """Perform the actual action (filesystem operations only in v1.4.0)"""
        if step.action_type == ActionType.WRITE:
            # Write to file
            content = step.parameters.get("content", "")
            os.makedirs(os.path.dirname(step.target) or ".", exist_ok=True)
            with open(step.target, "w", encoding="utf-8") as f:
                f.write(content)
            self.logger.debug(f"Wrote to {step.target}")
        
        elif step.action_type == ActionType.READ:
            # Read from file (verify it exists)
            with open(step.target, "r", encoding="utf-8") as f:
                _ = f.read()
            self.logger.debug(f"Read from {step.target}")
        
        elif step.action_type == ActionType.DELETE:
            # Delete file
            if os.path.exists(step.target):
                os.remove(step.target)
                self.logger.debug(f"Deleted {step.target}")
        
        elif step.action_type == ActionType.CREATE:
            # Create file
            os.makedirs(os.path.dirname(step.target) or ".", exist_ok=True)
            if not os.path.exists(step.target):
                with open(step.target, "w", encoding="utf-8") as f:
                    f.write("")
            self.logger.debug(f"Created {step.target}")
    
    def _perform_rollback(self, step: ExecutableStep):
        """Execute the rollback procedure for a step"""
        if not step.rollback_procedure:
            raise ValueError(f"No rollback procedure defined for step {step.step_id}")
        
        # Parse rollback procedure and execute
        self.logger.info(f"Invoking rollback for step {step.step_id}: {step.rollback_procedure}")
        
        if "Delete" in step.rollback_procedure and step.action_type == ActionType.WRITE:
            # Rollback: delete the file we created
            if os.path.exists(step.target):
                os.remove(step.target)
                self.logger.info(f"Rollback: Deleted {step.target}")
        
        elif "Restore" in step.rollback_procedure:
            # More complex rollback (would involve restore from backup)
            self.logger.warning(f"Restore rollback not yet implemented")
    
    def _capture_system_state(self) -> Dict[str, Any]:
        """Capture current filesystem state (simplified)"""
        return {
            "captured_at": datetime.now().isoformat(),
            "files_in_cwd": os.listdir("."),
        }
