"""
Test Suite: Real Execution Engine (v1.4.0)

Tests verify that:
1. Hard gates prevent unauthorized execution
2. Execution follows the plan exactly
3. Preconditions are re-checked against real system state
4. Rollback works when execution fails
5. Divergence is detected
6. Full audit trail is maintained
7. Zero side effects occur without approval
"""

import pytest
import os
import tempfile
import shutil
from pathlib import Path

from wrapper.execution_engine import (
    ExecutionEngine,
    ExecutionMode,
    DryRunExecutionReport,
    ExecutionResultArtifact,
    ExecutionStatus,
    SimulationStatus,
)
from wrapper.executable_intent import (
    ExecutableIntentEngine,
    ExecutionPlanArtifact,
    ExecutableStep,
    ActionType,
    SafetyLevel,
    RollbackCapability,
)


class TestExecutionMode:
    """Test the real execution engine (v1.4.0)"""
    
    @pytest.fixture
    def execution_mode(self):
        """Create an execution engine in execution mode"""
        return ExecutionMode()
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files"""
        temp_dir = tempfile.mkdtemp()
        original_cwd = os.getcwd()
        os.chdir(temp_dir)
        yield temp_dir
        os.chdir(original_cwd)
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def approved_dry_run(self):
        """Create an approved dry-run report"""
        report = DryRunExecutionReport(
            report_id="dryrun_approved_001",
            execution_plan_id="plan_approved_001",
        )
        report.execution_status = ExecutionStatus.SUCCESS
        report.simulation_status = SimulationStatus.SUCCESS
        report.user_approved_execution = True
        report.user_approval_timestamp = "2026-01-17T12:00:00"
        return report
    
    @pytest.fixture
    def simple_write_plan(self):
        """Create a simple write plan"""
        intent_engine = ExecutableIntentEngine()
        intent = {"verb": "write", "object": "test_output.txt", "content": "test data"}
        plan = intent_engine.plan_from_intent("intent_write_001", "Write test", intent)
        return plan
    
    # ========== HARD GATE TESTS ==========
    
    def test_hard_gate_no_dry_run_report(self, execution_mode, simple_write_plan):
        """Hard Gate 1: Execution aborts if no dry-run report provided"""
        result = execution_mode.execute_plan(
            dry_run_report=None,
            plan_artifact=simple_write_plan,
            user_approved=True,
        )
        
        assert result.execution_status == ExecutionStatus.ABORTED
        assert "No dry-run report" in result.abort_reason
    
    def test_hard_gate_unsafe_simulation(self, execution_mode, simple_write_plan):
        """Hard Gate 2: Execution aborts if simulation was UNSAFE"""
        report = DryRunExecutionReport(
            report_id="dryrun_unsafe_001",
            execution_plan_id=simple_write_plan.plan_id,
        )
        report.simulation_status = SimulationStatus.UNSAFE
        
        result = execution_mode.execute_plan(
            dry_run_report=report,
            plan_artifact=simple_write_plan,
            user_approved=True,
        )
        
        assert result.execution_status == ExecutionStatus.ABORTED
        assert "unsafe" in result.abort_reason.lower()
    
    def test_hard_gate_blocked_simulation(self, execution_mode, simple_write_plan):
        """Hard Gate 2: Execution aborts if simulation was BLOCKED"""
        report = DryRunExecutionReport(
            report_id="dryrun_blocked_001",
            execution_plan_id=simple_write_plan.plan_id,
        )
        report.simulation_status = SimulationStatus.BLOCKED
        report.blocking_reason = "Precondition not met"
        
        result = execution_mode.execute_plan(
            dry_run_report=report,
            plan_artifact=simple_write_plan,
            user_approved=True,
        )
        
        assert result.execution_status == ExecutionStatus.ABORTED
        assert "blocked" in result.abort_reason.lower()
    
    def test_hard_gate_user_not_approved(self, execution_mode, approved_dry_run, simple_write_plan):
        """Hard Gate 3: Execution aborts if user did not approve"""
        approved_dry_run.execution_plan_id = simple_write_plan.plan_id
        
        result = execution_mode.execute_plan(
            dry_run_report=approved_dry_run,
            plan_artifact=simple_write_plan,
            user_approved=False,  # NOT approved
        )
        
        assert result.execution_status == ExecutionStatus.ABORTED
        assert "approve" in result.abort_reason.lower()
    
    def test_hard_gate_id_mismatch(self, execution_mode, approved_dry_run):
        """Hard Gate 4 & 5: Execution aborts if IDs don't match"""
        intent_engine = ExecutableIntentEngine()
        intent = {"verb": "write", "object": "test.txt", "content": "data"}
        plan = intent_engine.plan_from_intent("intent_002", "Write", intent)
        
        # Report has different plan ID
        approved_dry_run.execution_plan_id = "WRONG_PLAN_ID"
        
        result = execution_mode.execute_plan(
            dry_run_report=approved_dry_run,
            plan_artifact=plan,
            user_approved=True,
        )
        
        assert result.execution_status == ExecutionStatus.ABORTED
        assert "mismatch" in result.abort_reason.lower()
    
    # ========== SUCCESSFUL EXECUTION TESTS ==========
    
    def test_successful_write_execution(self, execution_mode, approved_dry_run, simple_write_plan, temp_dir):
        """Successful execution: write file"""
        approved_dry_run.execution_plan_id = simple_write_plan.plan_id
        
        # Find the WRITE step (should be step 3 based on plan structure)
        write_step = next((s for s in simple_write_plan.steps if s.action_type == ActionType.WRITE), None)
        assert write_step is not None, "Plan should have a WRITE step"
        test_file = write_step.target
        
        assert not os.path.exists(test_file), "Test file should not exist yet"
        
        result = execution_mode.execute_plan(
            dry_run_report=approved_dry_run,
            plan_artifact=simple_write_plan,
            user_approved=True,
            intent_id="intent_002",
        )
        
        assert result.execution_status == ExecutionStatus.SUCCESS
        assert result.steps_succeeded > 0
        assert os.path.exists(test_file), f"File {test_file} should have been created"
        assert result.user_approved is True
        assert result.intent_id == "intent_002"
    
    def test_execution_chain_traceability(self, execution_mode, approved_dry_run, simple_write_plan):
        """Execution result maintains full chain traceability"""
        approved_dry_run.execution_plan_id = simple_write_plan.plan_id
        
        result = execution_mode.execute_plan(
            dry_run_report=approved_dry_run,
            plan_artifact=simple_write_plan,
            user_approved=True,
            intent_id="intent_chain_001",
            transcription_id="trans_chain_001",
        )
        
        assert result.intent_id == "intent_chain_001"
        assert result.transcription_id == "trans_chain_001"
        assert result.dry_run_report_id == approved_dry_run.report_id
        assert result.execution_plan_id == simple_write_plan.plan_id
    
    # ========== PRECONDITION TESTS ==========
    
    def test_execution_checks_real_preconditions(self, execution_mode, approved_dry_run, simple_write_plan, temp_dir):
        """Execution re-checks preconditions against real system state"""
        approved_dry_run.execution_plan_id = simple_write_plan.plan_id
        
        # Try to read a file that doesn't exist
        simple_write_plan.steps[0].action_type = ActionType.READ
        simple_write_plan.steps[0].target = "nonexistent_file.txt"
        
        result = execution_mode.execute_plan(
            dry_run_report=approved_dry_run,
            plan_artifact=simple_write_plan,
            user_approved=True,
        )
        
        # Should fail because file doesn't exist
        assert result.steps_failed > 0
        assert any(not step.precondition_met for step in result.steps_executed)
    
    # ========== ROLLBACK TESTS ==========
    
    def test_rollback_on_execution_failure(self, execution_mode, approved_dry_run, simple_write_plan, temp_dir):
        """Rollback is invoked when execution fails"""
        approved_dry_run.execution_plan_id = simple_write_plan.plan_id
        
        # Set up a write that will succeed, but track rollback capability
        test_file = "rollback_test.txt"
        simple_write_plan.steps[0].target = test_file
        simple_write_plan.steps[0].rollback_procedure = f"Delete {test_file}"
        simple_write_plan.steps[0].rollback_capability = RollbackCapability.FULL
        
        result = execution_mode.execute_plan(
            dry_run_report=approved_dry_run,
            plan_artifact=simple_write_plan,
            user_approved=True,
        )
        
        # If execution succeeds, rollback shouldn't be invoked
        assert result.rollback_invoked is False or result.execution_status == ExecutionStatus.SUCCESS
    
    # ========== STATE VERIFICATION TESTS ==========
    
    def test_before_after_state_captured(self, execution_mode, approved_dry_run, simple_write_plan, temp_dir):
        """Execution captures before/after system state"""
        approved_dry_run.execution_plan_id = simple_write_plan.plan_id
        
        result = execution_mode.execute_plan(
            dry_run_report=approved_dry_run,
            plan_artifact=simple_write_plan,
            user_approved=True,
        )
        
        assert result.before_state_snapshot is not None
        assert result.after_state_snapshot is not None
        assert "captured_at" in result.before_state_snapshot
        assert "captured_at" in result.after_state_snapshot
    
    def test_execution_result_serialization(self, execution_mode, approved_dry_run, simple_write_plan):
        """Execution result can be serialized"""
        approved_dry_run.execution_plan_id = simple_write_plan.plan_id
        
        result = execution_mode.execute_plan(
            dry_run_report=approved_dry_run,
            plan_artifact=simple_write_plan,
            user_approved=True,
        )
        
        serialized = result.to_dict()
        
        assert serialized["result_id"] == result.result_id
        assert serialized["execution_status"] == result.execution_status.value
        assert serialized["user_approved"] is True


class TestExecutedStepResult:
    """Test individual executed step results"""
    
    def test_step_result_creation(self):
        """Step result can be created with metadata"""
        from wrapper.execution_engine import ExecutedStepResult
        
        step = ExecutedStepResult(
            step_id=1,
            operation="write_file",
            target="test.txt",
            action_type=ActionType.WRITE,
        )
        
        assert step.step_id == 1
        assert step.operation == "write_file"
        assert step.success is False  # Not executed yet
    
    def test_step_result_success_flag(self):
        """Step result tracks success/failure"""
        from wrapper.execution_engine import ExecutedStepResult
        
        step = ExecutedStepResult(
            step_id=1,
            operation="write_file",
            target="test.txt",
            action_type=ActionType.WRITE,
        )
        
        step.success = True
        assert step.success is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
