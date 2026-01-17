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
