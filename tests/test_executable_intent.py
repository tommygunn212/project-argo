"""
Test Suite: Executable Intent Layer (v1.2.0)

Tests verify that:
1. Intents are correctly translated to executable plans
2. Plans include proper safety metadata
3. Rollback procedures are defined for state-changing actions
4. Alternative approaches are considered where appropriate
5. All plans maintain auditability and determinism
6. No actual execution occurs (this is just planning)
"""

import pytest
import json
import os
from datetime import datetime

from wrapper.executable_intent import (
    ExecutableIntentEngine,
    ExecutionPlanArtifact,
    ExecutableStep,
    PlanDeriver,
    ExecutionPlanArtifactStorage,
    ActionType,
    SafetyLevel,
    RollbackCapability,
)


class TestExecutableStep:
    """Test individual executable steps"""
    
    def test_step_creation(self):
        """Step can be created with all metadata"""
        step = ExecutableStep(
            step_id=1,
            action_type=ActionType.WRITE,
            target="test.txt",
            operation="create_file",
            parameters={"path": "test.txt", "content": "test"},
            safety_level=SafetyLevel.CAUTIOUS,
            rollback_capability=RollbackCapability.FULL,
            rollback_procedure="Delete file",
        )
        
        assert step.step_id == 1
        assert step.target == "test.txt"
        assert step.safety_level == SafetyLevel.CAUTIOUS
    
    def test_step_serialization(self):
        """Step can be serialized to dict"""
        step = ExecutableStep(
            step_id=1,
            action_type=ActionType.READ,
            target="data.json",
            operation="load_file",
            parameters={"path": "data.json"},
        )
        
        serialized = step.to_dict()
        
        assert serialized["step_id"] == 1
        assert serialized["action_type"] == "read"
        assert "timestamp" in serialized


class TestExecutablePlan:
    """Test plan artifact creation and management"""
    
    def test_plan_creation(self):
        """Plan artifact can be created with metadata"""
        plan = ExecutionPlanArtifact(
            plan_id="plan_test_001",
            intent_id="intent_test_001",
            intent_text="Write a file",
        )
        
        assert plan.plan_id == "plan_test_001"
        assert plan.intent_id == "intent_test_001"
        assert len(plan.steps) == 0
    
    def test_add_step_updates_metadata(self):
        """Adding steps updates plan artifact metadata"""
        plan = ExecutionPlanArtifact(
            plan_id="plan_test_001",
            intent_id="intent_test_001",
            intent_text="Do something",
        )
        
        # Add a safe step
        safe_step = ExecutableStep(
            step_id=1,
            action_type=ActionType.READ,
            target="file.txt",
            operation="read",
            parameters={},
            safety_level=SafetyLevel.SAFE,
        )
        plan.add_step(safe_step)
        
        assert plan.highest_risk_level == SafetyLevel.SAFE
        assert plan.total_confirmations_needed == 0
        
        # Add a risky step with confirmations
        risky_step = ExecutableStep(
            step_id=2,
            action_type=ActionType.DELETE,
            target="file.txt",
            operation="delete",
            parameters={"path": "file.txt"},
            safety_level=SafetyLevel.CRITICAL,
            required_confirmations=["confirm_delete", "confirm_permanent"],
        )
        plan.add_step(risky_step)
        
        assert plan.highest_risk_level == SafetyLevel.CRITICAL
        assert plan.total_confirmations_needed == 2
    
    def test_irreversible_action_detection(self):
        """Plan artifact detects actions that cannot be fully rolled back"""
        plan = ExecutionPlanArtifact(
            plan_id="plan_test_001",
            intent_id="intent_test_001",
            intent_text="Delete permanently",
        )
        
        # Add reversible step
        step1 = ExecutableStep(
            step_id=1,
            action_type=ActionType.WRITE,
            target="file.txt",
            operation="write",
            parameters={},
            rollback_capability=RollbackCapability.FULL,
        )
        plan.add_step(step1)
        assert plan.can_fully_rollback is True
        
        # Add irreversible step
        step2 = ExecutableStep(
            step_id=2,
            action_type=ActionType.DELETE,
            target="file.txt",
            operation="delete",
            parameters={},
            rollback_capability=RollbackCapability.NONE,
        )
        plan.add_step(step2)
        assert plan.can_fully_rollback is False
        assert plan.has_irreversible_actions is True
    
    def test_plan_summary(self):
        """Plan artifact summary is human readable"""
        plan = ExecutionPlanArtifact(
            plan_id="plan_test_001",
            intent_id="intent_test_001",
            intent_text="Write a test file",
        )
        
        step = ExecutableStep(
            step_id=1,
            action_type=ActionType.WRITE,
            target="test.txt",
            operation="write_file",
            parameters={"content": "test"},
            safety_level=SafetyLevel.CAUTIOUS,
            required_confirmations=["confirm_write"],
        )
        plan.add_step(step)
        
        summary = plan.summary()
        
        assert "plan_test_001" in summary
        assert "Write a test file" in summary
        assert "1 steps" in summary or "1." in summary
        assert "CAUTIOUS" in summary


class TestPlanDeriver:
    """Test the plan derivation engine"""
    
    @pytest.fixture
    def deriver(self):
        """Create a PlanDeriver for testing"""
        return PlanDeriver()
    
    def test_derive_write_plan(self, deriver):
        """Derive a write plan from write intent"""
        intent = {
            "verb": "write",
            "object": "document.txt",
            "content": "Hello, world!",
            "context": "",
        }
        
        plan = deriver.derive("intent_001", "Write to document.txt", intent)
        
        assert plan.intent_id == "intent_001"
        assert len(plan.steps) == 3  # check exists, backup, write
        assert plan.steps[0].operation == "check_exists"
        assert plan.steps[1].operation == "backup_existing"
        assert plan.steps[2].operation == "write_file"
        assert plan.steps[2].safety_level == SafetyLevel.CAUTIOUS
    
    def test_derive_open_plan(self, deriver):
        """Derive an open plan from open intent"""
        intent = {
            "verb": "open",
            "object": "report.pdf",
            "context": "",
        }
        
        plan = deriver.derive("intent_002", "Open report.pdf", intent)
        
        assert len(plan.steps) == 2  # locate, open
        assert plan.steps[0].operation == "locate"
        assert plan.steps[1].operation == "open"
        assert plan.steps[1].safety_level == SafetyLevel.SAFE
    
    def test_derive_save_plan(self, deriver):
        """Derive a save plan from save intent"""
        intent = {
            "verb": "save",
            "object": "/home/user/documents/file.txt",
            "context": "",
        }
        
        plan = deriver.derive("intent_003", "Save to file.txt", intent)
        
        assert len(plan.steps) == 2  # check path, save
        assert plan.steps[0].operation == "check_path"
        assert plan.steps[1].operation == "save_document"
    
    def test_derive_show_plan(self, deriver):
        """Derive a show plan from show intent"""
        intent = {
            "verb": "show",
            "object": "dashboard",
            "context": "",
        }
        
        plan = deriver.derive("intent_004", "Show dashboard", intent)
        
        assert len(plan.steps) == 2  # load, display
        assert plan.steps[0].operation == "load"
        assert plan.steps[1].operation == "show"
    
    def test_derive_search_plan(self, deriver):
        """Derive a search plan from search intent"""
        intent = {
            "verb": "search",
            "object": "python files",
            "context": "local",
        }
        
        plan = deriver.derive("intent_005", "Search for python files", intent)
        
        assert len(plan.steps) == 3  # prepare, search, display results
        assert plan.steps[0].operation == "prepare_query"
        assert plan.steps[1].operation == "search"
        assert plan.steps[2].operation == "show_results"
    
    def test_unknown_verb_fallback(self, deriver):
        """Unknown verbs fall back to generic plan"""
        intent = {
            "verb": "teleport",
            "object": "mars",
            "context": "",
        }
        
        plan = deriver.derive("intent_006", "Teleport to mars", intent)
        
        assert len(plan.steps) >= 1
        assert plan.steps[0].safety_level == SafetyLevel.SAFE
    
    def test_plan_determinism(self, deriver):
        """Same intent always produces same plan structure"""
        intent = {
            "verb": "write",
            "object": "test.txt",
            "content": "test content",
        }
        
        plan1 = deriver.derive("intent_007a", "Write test", intent)
        plan2 = deriver.derive("intent_007b", "Write test", intent)
        
        # Plans should have same number of steps and same operations
        assert len(plan1.steps) == len(plan2.steps)
        for s1, s2 in zip(plan1.steps, plan2.steps):
            assert s1.operation == s2.operation
            assert s1.action_type == s2.action_type


class TestExecutablePlanStorage:
    """Test plan storage and retrieval"""
    
    @pytest.fixture
    def storage(self, tmp_path):
        """Create storage with temporary directory"""
        return ExecutionPlanArtifactStorage(log_dir=str(tmp_path))
    
    def test_store_and_retrieve(self, storage):
        """Store plan artifact and retrieve it"""
        plan = ExecutionPlanArtifact(
            plan_id="plan_test_001",
            intent_id="intent_test_001",
            intent_text="Test plan",
        )
        
        plan_id = storage.store(plan)
        
        assert plan_id == "plan_test_001"
        
        retrieved = storage.retrieve(plan_id)
        assert retrieved is not None
        assert retrieved.intent_text == "Test plan"
    
    def test_list_plans(self, storage):
        """List all stored plan artifacts"""
        plan1 = ExecutionPlanArtifact("plan_001", "intent_001", "Test 1")
        plan2 = ExecutionPlanArtifact("plan_002", "intent_002", "Test 2")
        
        storage.store(plan1)
        storage.store(plan2)
        
        plans = storage.list_plans()
        
        assert len(plans) == 2
        assert "plan_001" in plans
        assert "plan_002" in plans
    
    def test_retrieve_nonexistent(self, storage):
        """Retrieving nonexistent plan returns None"""
        result = storage.retrieve("plan_doesnotexist")
        assert result is None
    
    def test_plan_logging(self, storage, tmp_path):
        """Plan artifacts are logged to file"""
        plan = ExecutionPlanArtifact(
            plan_id="plan_test_001",
            intent_id="intent_test_001",
            intent_text="Test logging",
        )
        
        step = ExecutableStep(
            step_id=1,
            action_type=ActionType.READ,
            target="file.txt",
            operation="read",
            parameters={},
        )
        plan.add_step(step)
        
        storage.store(plan)
        
        log_file = tmp_path / "executable_plans.log"
        assert log_file.exists()
        
        content = log_file.read_text()
        assert "plan_test_001" in content
        assert "intent_test_001" in content


class TestExecutableIntentEngine:
    """Integration tests for the full engine"""
    
    @pytest.fixture
    def engine(self, tmp_path):
        """Create engine with temporary log directory"""
        return ExecutableIntentEngine(log_dir=str(tmp_path))
    
    def test_engine_creation(self, engine):
        """Engine initializes correctly"""
        assert engine.deriver is not None
        assert engine.storage is not None
        assert engine.logger is not None
    
    def test_plan_from_intent(self, engine):
        """Engine converts intent to plan artifact"""
        intent = {
            "verb": "write",
            "object": "test.txt",
            "content": "Hello",
        }
        
        plan = engine.plan_from_intent(
            intent_id="intent_001",
            intent_text="Write test file",
            parsed_intent=intent
        )
        
        assert plan.intent_id == "intent_001"
        assert len(plan.steps) > 0
    
    def test_plan_retrieval(self, engine):
        """Engine can retrieve stored plan artifacts"""
        intent = {
            "verb": "open",
            "object": "file.txt",
        }
        
        plan = engine.plan_from_intent(
            intent_id="intent_002",
            intent_text="Open file",
            parsed_intent=intent
        )
        
        retrieved = engine.get_plan(plan.plan_id)
        assert retrieved is not None
        assert retrieved.plan_id == plan.plan_id
    
    def test_list_all_plans(self, engine):
        """Engine lists all plans"""
        for i in range(3):
            intent = {"verb": "open", "object": f"file{i}.txt"}
            engine.plan_from_intent(
                intent_id=f"intent_{i}",
                intent_text=f"Open file{i}",
                parsed_intent=intent
            )
        
        plans = engine.list_all_plans()
        assert len(plans) == 3
    
    def test_no_execution_occurs(self, engine):
        """Plans are created but not executed"""
        # This is critical: the executable intent layer should NOT execute anything
        
        intent = {
            "verb": "write",
            "object": "should_not_exist.txt",
            "content": "This file should not be created",
        }
        
        plan = engine.plan_from_intent(
            intent_id="intent_no_exec",
            intent_text="Write file that should not exist",
            parsed_intent=intent
        )
        
        # Plan was created
        assert plan.plan_id is not None
        
        # But file should NOT exist
        assert not os.path.exists("should_not_exist.txt"), \
            "CRITICAL: Executable intent layer executed plan without authorization"


class TestSafetyAndAuditability:
    """Test safety features and audit trail"""
    
    def test_write_operation_safety(self):
        """Write operations include backup and confirmation steps"""
        deriver = PlanDeriver()
        intent = {
            "verb": "write",
            "object": "critical.txt",
            "content": "Important data",
            "context": "exists",
        }
        
        plan = deriver.derive("intent_safe_001", "Write critical", intent)
        
        # Should have backup step
        backup_steps = [s for s in plan.steps if "backup" in s.operation]
        assert len(backup_steps) > 0
        
        # Should have confirmation on write
        write_steps = [s for s in plan.steps if "write" in s.operation]
        assert len(write_steps) > 0
        assert len(write_steps[0].required_confirmations) > 0
    
    def test_delete_operation_requires_confirmation(self):
        """Delete operations require explicit confirmation"""
        # Note: This test verifies the safety model for future v1.3.0
        # v1.2.0 doesn't implement delete yet, but we define the principle
        
        step = ExecutableStep(
            step_id=1,
            action_type=ActionType.DELETE,
            target="file.txt",
            operation="delete_file",
            parameters={"path": "file.txt"},
            safety_level=SafetyLevel.CRITICAL,
            rollback_capability=RollbackCapability.NONE,
            required_confirmations=["confirm_delete", "confirm_permanent"],
        )
        
        assert step.safety_level == SafetyLevel.CRITICAL
        assert len(step.required_confirmations) >= 1
    
    def test_rollback_procedures_defined(self):
        """State-changing operations have rollback procedures"""
        deriver = PlanDeriver()
        intent = {
            "verb": "write",
            "object": "test.txt",
            "content": "test",
        }
        
        plan = deriver.derive("intent_rollback", "Write test", intent)
        
        state_changing_steps = [
            s for s in plan.steps 
            if s.action_type in (ActionType.WRITE, ActionType.DELETE, ActionType.CREATE)
        ]
        
        for step in state_changing_steps:
            if step.rollback_capability != RollbackCapability.NONE:
                # Should have a rollback procedure
                assert step.rollback_procedure is not None or step.rollback_capability == RollbackCapability.PARTIAL


class TestDeterminism:
    """Test that planning is deterministic"""
    
    def test_same_intent_same_plan_structure(self):
        """Same intent always produces plan with same structure"""
        engine = ExecutableIntentEngine()
        
        intent = {
            "verb": "open",
            "object": "document.pdf",
        }
        
        plans = [
            engine.plan_from_intent(f"intent_{i}", "Open document", intent)
            for i in range(5)
        ]
        
        # All plans should have same number of steps with same operations
        for plan in plans[1:]:
            assert len(plan.steps) == len(plans[0].steps)
            for s1, s2 in zip(plan.steps, plans[0].steps):
                assert s1.operation == s2.operation
                assert s1.action_type == s2.action_type


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
