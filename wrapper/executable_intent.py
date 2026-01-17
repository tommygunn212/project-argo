"""
Executable Intent Layer (v1.2.0)

Transforms validated intents into concrete, executable plans.
Plans describe WHAT will happen and HOW it will happen, but do NOT execute.
Every plan is explicit, reversible, and requires confirmation before execution.

Design:
- IntentArtifact (v1.1.0: "user wants X") → ExecutablePlan (v1.2.0: "here's how we do X")
- Plans are deterministic: same intent → same plan every time
- Plans include rollback instructions, resource costs, and safety constraints
- All plans logged with full context and reasoning
- User confirms PLAN before execution layer (v1.3.0) runs it
"""

import json
import logging
import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field
from enum import Enum
import os

# ============================================================================
# ENUMS & CONSTANTS
# ============================================================================

class ActionType(Enum):
    """Executable action categories"""
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    CREATE = "create"
    MODIFY = "modify"
    CONTROL = "control"
    QUERY = "query"
    DISPLAY = "display"


class SafetyLevel(Enum):
    """Risk assessment for each action"""
    SAFE = "safe"  # No state change, read-only
    CAUTIOUS = "cautious"  # State change, reversible
    RISKY = "risky"  # State change, partially reversible
    CRITICAL = "critical"  # Irreversible, high impact


class RollbackCapability(Enum):
    """Can we undo this action?"""
    FULL = "full"  # Complete rollback possible
    PARTIAL = "partial"  # Can mitigate but not fully revert
    NONE = "none"  # No rollback possible


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class ExecutableStep:
    """Single step in an executable plan"""
    
    step_id: int
    action_type: ActionType
    target: str  # What are we acting on? (file, device, system, etc.)
    operation: str  # What are we doing? (open, create, write, etc.)
    parameters: Dict[str, Any]  # Operation-specific parameters
    
    safety_level: SafetyLevel = SafetyLevel.SAFE
    rollback_capability: RollbackCapability = RollbackCapability.NONE
    rollback_procedure: Optional[str] = None
    
    required_confirmations: List[str] = field(default_factory=list)
    resource_cost: Optional[Dict[str, Any]] = None
    constraints: List[str] = field(default_factory=list)
    
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage"""
        return {
            "step_id": self.step_id,
            "action_type": self.action_type.value,
            "target": self.target,
            "operation": self.operation,
            "parameters": self.parameters,
            "safety_level": self.safety_level.value,
            "rollback_capability": self.rollback_capability.value,
            "rollback_procedure": self.rollback_procedure,
            "required_confirmations": self.required_confirmations,
            "resource_cost": self.resource_cost,
            "constraints": self.constraints,
            "timestamp": self.timestamp,
        }


@dataclass
class ExecutionPlanArtifact:
    """Complete plan derived from an intent, ready for execution (but not executing)
    
    This is an artifact, not an execution. No actions occur during plan creation.
    Plans are created but NOT executed by this layer.
    """
    
    plan_id: str
    intent_id: str  # Reference to the IntentArtifact that created this
    intent_text: str  # Original user utterance
    
    steps: List[ExecutableStep] = field(default_factory=list)
    
    # Plan-level metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    derived_from: str = "intent"  # Always "intent" for v1.2.0
    
    # Risk analysis
    highest_risk_level: SafetyLevel = SafetyLevel.SAFE
    has_irreversible_actions: bool = False
    total_confirmations_needed: int = 0
    
    # Rollback info
    can_fully_rollback: bool = True
    rollback_cost: Optional[str] = None  # Describe effort to undo
    
    # Alternative plans (if derivation found multiple approaches)
    alternatives: List['ExecutablePlan'] = field(default_factory=list)
    chosen_reason: Optional[str] = None
    
    # Execution readiness
    status: str = "derived"  # derived → user_reviewing → awaiting_confirmation → ready_for_execution
    
    # Versioning
    schema_version: str = "1.2.0"
    
    def add_step(self, step: ExecutableStep) -> None:
        """Add a step and update plan metadata"""
        self.steps.append(step)
        
        # Update risk level (using enum order: SAFE < CAUTIOUS < RISKY < CRITICAL)
        risk_order = {SafetyLevel.SAFE: 0, SafetyLevel.CAUTIOUS: 1, SafetyLevel.RISKY: 2, SafetyLevel.CRITICAL: 3}
        current_risk = risk_order.get(self.highest_risk_level, 0)
        new_risk = risk_order.get(step.safety_level, 0)
        if new_risk > current_risk:
            self.highest_risk_level = step.safety_level
        
        # Track irreversible actions
        if step.rollback_capability == RollbackCapability.NONE:
            self.has_irreversible_actions = True
        
        # Count confirmations
        self.total_confirmations_needed += len(step.required_confirmations)
        
        # Track rollback capability
        if step.rollback_capability != RollbackCapability.FULL:
            self.can_fully_rollback = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage"""
        return {
            "plan_id": self.plan_id,
            "intent_id": self.intent_id,
            "intent_text": self.intent_text,
            "steps": [step.to_dict() for step in self.steps],
            "created_at": self.created_at,
            "derived_from": self.derived_from,
            "highest_risk_level": self.highest_risk_level.value,
            "has_irreversible_actions": self.has_irreversible_actions,
            "total_confirmations_needed": self.total_confirmations_needed,
            "can_fully_rollback": self.can_fully_rollback,
            "rollback_cost": self.rollback_cost,
            "status": self.status,
            "schema_version": self.schema_version,
        }
    
    def summary(self) -> str:
        """Human-readable plan summary"""
        lines = [
            f"Plan: {self.plan_id}",
            f"From Intent: {self.intent_id}",
            f"User Said: \"{self.intent_text}\"",
            f"",
            f"Steps: {len(self.steps)}",
            f"Confirmations Needed: {self.total_confirmations_needed}",
            f"Risk Level: {self.highest_risk_level.value.upper()}",
            f"Fully Reversible: {'Yes' if self.can_fully_rollback else 'No (has irreversible actions)'}",
            f"",
            "Plan Steps:",
        ]
        
        for step in self.steps:
            lines.append(f"  {step.step_id}. {step.operation.upper()} {step.target}")
            lines.append(f"     Action Type: {step.action_type.value}")
            lines.append(f"     Safety: {step.safety_level.value.upper()}")
            if step.required_confirmations:
                lines.append(f"     Requires: {', '.join(step.required_confirmations)}")
            if step.constraints:
                lines.append(f"     Constraints: {', '.join(step.constraints)}")
        
        return "\n".join(lines)


# ============================================================================
# PLAN DERIVATION ENGINE
# ============================================================================

class PlanDeriver:
    """
    Derives executable plans from validated intents.
    This is the planning layer: analyzes what to do without doing it.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.derivation_rules = self._load_derivation_rules()
    
    def _load_derivation_rules(self) -> Dict[str, Any]:
        """Load rules for translating intents to plans"""
        return {
            "write": self._derive_write_plan,
            "open": self._derive_open_plan,
            "save": self._derive_save_plan,
            "show": self._derive_show_plan,
            "search": self._derive_search_plan,
        }
    
    def derive(self, intent_id: str, intent_text: str, parsed_intent: Dict[str, Any]) -> ExecutionPlanArtifact:
        """
        Main derivation entry point.
        Input: A validated intent from IntentArtifact
        Output: An executable plan (not executed)
        """
        
        verb = parsed_intent.get("verb")
        self.logger.info(f"Deriving plan for intent {intent_id}: {verb}")
        
        plan = ExecutionPlanArtifact(
            plan_id=self._generate_plan_id(intent_id),
            intent_id=intent_id,
            intent_text=intent_text,
        )
        
        # Route to appropriate deriver
        if verb in self.derivation_rules:
            self.derivation_rules[verb](plan, parsed_intent)
        else:
            self.logger.warning(f"No derivation rule for verb: {verb}")
            self._derive_generic_plan(plan, parsed_intent)
        
        # Log plan creation
        self.logger.info(f"Plan derived: {plan.plan_id} with {len(plan.steps)} steps")
        return plan
    
    def _derive_write_plan(self, plan: ExecutionPlanArtifact, intent: Dict[str, Any]) -> None:
        """Plan: Create/modify a file with content"""
        
        filepath = intent.get("object", "unknown_file")
        content = intent.get("content", "")
        
        # Step 1: Check if file exists
        step1 = ExecutableStep(
            step_id=1,
            action_type=ActionType.QUERY,
            target=filepath,
            operation="check_exists",
            parameters={"path": filepath},
            safety_level=SafetyLevel.SAFE,
            rollback_capability=RollbackCapability.FULL,
        )
        plan.add_step(step1)
        
        # Step 2: Create backup if file exists
        step2 = ExecutableStep(
            step_id=2,
            action_type=ActionType.CREATE,
            target=f"{filepath}.backup",
            operation="backup_existing",
            parameters={"original": filepath, "backup_suffix": ".backup"},
            safety_level=SafetyLevel.CAUTIOUS,
            rollback_capability=RollbackCapability.FULL,
            rollback_procedure=f"Restore from {filepath}.backup",
            constraints=["Only if file exists"],
        )
        plan.add_step(step2)
        
        # Step 3: Write new content
        step3 = ExecutableStep(
            step_id=3,
            action_type=ActionType.WRITE,
            target=filepath,
            operation="write_file",
            parameters={"path": filepath, "content": content, "mode": "w"},
            safety_level=SafetyLevel.CAUTIOUS,
            rollback_capability=RollbackCapability.FULL,
            rollback_procedure=f"Restore from {filepath}.backup",
            required_confirmations=["confirm_overwrite" if "exists" in intent.get("context", "") else "confirm_create"],
        )
        plan.add_step(step3)
        
        self.logger.info(f"Write plan: {len(plan.steps)} steps to {filepath}")
    
    def _derive_open_plan(self, plan: ExecutionPlanArtifact, intent: Dict[str, Any]) -> None:
        """Plan: Open a file or application"""
        
        target = intent.get("object", "unknown")
        
        # Step 1: Locate file/app
        step1 = ExecutableStep(
            step_id=1,
            action_type=ActionType.QUERY,
            target=target,
            operation="locate",
            parameters={"name": target, "search_paths": ["current", "recent", "system"]},
            safety_level=SafetyLevel.SAFE,
            rollback_capability=RollbackCapability.FULL,
        )
        plan.add_step(step1)
        
        # Step 2: Open
        step2 = ExecutableStep(
            step_id=2,
            action_type=ActionType.CONTROL,
            target=target,
            operation="open",
            parameters={"path": target},
            safety_level=SafetyLevel.SAFE,
            rollback_capability=RollbackCapability.FULL,
            rollback_procedure="Close window/application",
        )
        plan.add_step(step2)
        
        self.logger.info(f"Open plan: {len(plan.steps)} steps to open {target}")
    
    def _derive_save_plan(self, plan: ExecutionPlanArtifact, intent: Dict[str, Any]) -> None:
        """Plan: Save current document to a location"""
        
        filepath = intent.get("object", "document")
        
        # Step 1: Check target location exists/is writable
        step1 = ExecutableStep(
            step_id=1,
            action_type=ActionType.QUERY,
            target=filepath,
            operation="check_path",
            parameters={"path": filepath},
            safety_level=SafetyLevel.SAFE,
            rollback_capability=RollbackCapability.FULL,
        )
        plan.add_step(step1)
        
        # Step 2: Save to location
        step2 = ExecutableStep(
            step_id=2,
            action_type=ActionType.WRITE,
            target=filepath,
            operation="save_document",
            parameters={"path": filepath},
            safety_level=SafetyLevel.CAUTIOUS,
            rollback_capability=RollbackCapability.PARTIAL,
            rollback_procedure="Delete saved file",
            required_confirmations=["confirm_save_location"],
        )
        plan.add_step(step2)
        
        self.logger.info(f"Save plan: {len(plan.steps)} steps to save to {filepath}")
    
    def _derive_show_plan(self, plan: ExecutionPlanArtifact, intent: Dict[str, Any]) -> None:
        """Plan: Display content on screen"""
        
        content = intent.get("object", "unknown")
        
        # Step 1: Prepare content
        step1 = ExecutableStep(
            step_id=1,
            action_type=ActionType.READ,
            target=content,
            operation="load",
            parameters={"content_id": content},
            safety_level=SafetyLevel.SAFE,
            rollback_capability=RollbackCapability.FULL,
        )
        plan.add_step(step1)
        
        # Step 2: Display
        step2 = ExecutableStep(
            step_id=2,
            action_type=ActionType.DISPLAY,
            target="primary_display",
            operation="show",
            parameters={"content": content},
            safety_level=SafetyLevel.SAFE,
            rollback_capability=RollbackCapability.FULL,
            rollback_procedure="Clear display",
        )
        plan.add_step(step2)
        
        self.logger.info(f"Show plan: {len(plan.steps)} steps to display {content}")
    
    def _derive_search_plan(self, plan: ExecutionPlanArtifact, intent: Dict[str, Any]) -> None:
        """Plan: Search for something (files, content, etc.)"""
        
        query = intent.get("object", "")
        search_scope = intent.get("context", "local")
        
        # Step 1: Build search query
        step1 = ExecutableStep(
            step_id=1,
            action_type=ActionType.QUERY,
            target="search_engine",
            operation="prepare_query",
            parameters={"query": query, "scope": search_scope},
            safety_level=SafetyLevel.SAFE,
            rollback_capability=RollbackCapability.FULL,
        )
        plan.add_step(step1)
        
        # Step 2: Execute search
        step2 = ExecutableStep(
            step_id=2,
            action_type=ActionType.READ,
            target="file_system",
            operation="search",
            parameters={"query": query, "scope": search_scope},
            safety_level=SafetyLevel.SAFE,
            rollback_capability=RollbackCapability.FULL,
        )
        plan.add_step(step2)
        
        # Step 3: Display results
        step3 = ExecutableStep(
            step_id=3,
            action_type=ActionType.DISPLAY,
            target="results",
            operation="show_results",
            parameters={"max_results": 20},
            safety_level=SafetyLevel.SAFE,
            rollback_capability=RollbackCapability.FULL,
        )
        plan.add_step(step3)
        
        self.logger.info(f"Search plan: {len(plan.steps)} steps for '{query}'")
    
    def _derive_generic_plan(self, plan: ExecutionPlanArtifact, intent: Dict[str, Any]) -> None:
        """Fallback: Generic plan for unknown intents"""
        
        step = ExecutableStep(
            step_id=1,
            action_type=ActionType.QUERY,
            target="unknown",
            operation=intent.get("verb", "unknown"),
            parameters=intent,
            safety_level=SafetyLevel.SAFE,
            rollback_capability=RollbackCapability.NONE,
        )
        plan.add_step(step)
        
        self.logger.warning(f"Generic plan for unrecognized intent: {intent}")
    
    def _generate_plan_id(self, intent_id: str) -> str:
        """Generate unique plan ID from intent ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        base = f"{intent_id}_{timestamp}"
        return f"plan_{hashlib.sha256(base.encode()).hexdigest()[:12]}"


# ============================================================================
# PLAN STORAGE
# ============================================================================

class ExecutionPlanArtifactStorage:
    """Session-only storage of execution plan artifacts"""
    
    def __init__(self, log_dir: str = "runtime/logs", logger: Optional[logging.Logger] = None):
        self.log_dir = log_dir
        self.logger = logger or logging.getLogger(__name__)
        self.plans: Dict[str, ExecutionPlanArtifact] = {}
        self._ensure_log_dir()
    
    def _ensure_log_dir(self) -> None:
        """Ensure log directory exists"""
        os.makedirs(self.log_dir, exist_ok=True)
    
    def store(self, plan: ExecutionPlanArtifact) -> str:
        """Store plan artifact and return ID"""
        self.plans[plan.plan_id] = plan
        self._log_plan(plan)
        self.logger.info(f"Stored plan: {plan.plan_id}")
        return plan.plan_id
    
    def retrieve(self, plan_id: str) -> Optional[ExecutionPlanArtifact]:
        """Retrieve plan artifact by ID"""
        return self.plans.get(plan_id)
    
    def list_plans(self) -> List[str]:
        """List all stored plan IDs"""
        return list(self.plans.keys())
    
    def _log_plan(self, plan: ExecutionPlanArtifact) -> None:
        """Log plan artifact to file"""
        log_file = os.path.join(self.log_dir, "executable_plans.log")
        try:
            with open(log_file, "a") as f:
                f.write(f"\n--- {plan.created_at} ---\n")
                f.write(f"Plan ID: {plan.plan_id}\n")
                f.write(f"Intent ID: {plan.intent_id}\n")
                f.write(f"Intent Text: {plan.intent_text}\n")
                f.write(f"Steps: {len(plan.steps)}\n")
                f.write(f"Risk Level: {plan.highest_risk_level.value}\n")
                f.write(f"Status: {plan.status}\n")
                f.write(json.dumps(plan.to_dict(), indent=2))
                f.write("\n")
        except Exception as e:
            self.logger.error(f"Failed to log plan: {e}")


# ============================================================================
# MAIN EXECUTABLE INTENT INTERFACE
# ============================================================================

class ExecutableIntentEngine:
    """
    Main interface for v1.2.0: Executable Intent Layer
    
    Converts user intents into explicit, auditable execution plans.
    Plans can be reviewed, modified, and confirmed before execution.
    
    Plan artifacts are created but NOT executed by this layer.
    """
    
    def __init__(self, log_dir: str = "runtime/logs"):
        self.logger = self._setup_logging(log_dir)
        self.deriver = PlanDeriver(self.logger)
        self.storage = ExecutionPlanArtifactStorage(log_dir, self.logger)
    
    def _setup_logging(self, log_dir: str) -> logging.Logger:
        """Configure logging for executable intent layer"""
        os.makedirs(log_dir, exist_ok=True)
        
        logger = logging.getLogger("executable_intent")
        logger.setLevel(logging.DEBUG)
        
        handler = logging.FileHandler(os.path.join(log_dir, "executable_intent.log"))
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        return logger
    
    def plan_from_intent(self, intent_id: str, intent_text: str, parsed_intent: Dict[str, Any]) -> ExecutionPlanArtifact:
        """
        Convert a validated intent into an executable plan.
        
        Args:
            intent_id: Unique ID from IntentArtifact
            intent_text: Original user utterance
            parsed_intent: Parsed intent from IntentArtifact (verb, object, context, etc.)
        
        Returns:
            ExecutionPlanArtifact: A plan describing what will happen, ready for user review
        """
        plan = self.deriver.derive(intent_id, intent_text, parsed_intent)
        self.storage.store(plan)
        return plan
    
    def get_plan(self, plan_id: str) -> Optional[ExecutionPlanArtifact]:
        """Retrieve a stored plan"""
        return self.storage.retrieve(plan_id)
    
    def list_all_plans(self) -> List[str]:
        """List all plans in this session"""
        return self.storage.list_plans()


# ============================================================================
# TEST UTILITIES
# ============================================================================

if __name__ == "__main__":
    # Quick smoke test
    engine = ExecutableIntentEngine()
    
    # Simulate an intent from IntentArtifact
    test_intent = {
        "verb": "write",
        "object": "test_document.txt",
        "content": "This is a test document.",
        "context": "user wants to create file"
    }
    
    plan = engine.plan_from_intent(
        intent_id="intent_test_001",
        intent_text="Write a new file called test_document.txt",
        parsed_intent=test_intent
    )
    
    print(plan.summary())
    print(f"\nPlan ID: {plan.plan_id}")
    print(f"Status: {plan.status}")
