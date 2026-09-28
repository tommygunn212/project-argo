from enum import Enum
from types import SimpleNamespace
from unittest.mock import Mock

from wrapper.execution_workflow import ExecutionWorkflow, execute_approved_plan


class SimulationStatus(Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"


class ExecutionStatus(Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    ROLLED_BACK = "rolled_back"
    ABORTED = "aborted"


def _workflow(result=None):
    mode = SimpleNamespace(execute_plan=Mock(return_value=result))
    factory = Mock(return_value=mode)
    return (
        ExecutionWorkflow(True, factory, SimulationStatus, ExecutionStatus),
        factory,
        mode,
    )


def _report(status=SimulationStatus.SUCCESS, plan_id="plan-1"):
    return SimpleNamespace(
        simulation_status=status,
        blocking_reason="blocked" if status is SimulationStatus.BLOCKED else None,
        execution_plan_id=plan_id,
    )


def test_missing_report_stops_before_execution():
    workflow, factory, _mode = _workflow()

    assert execute_approved_plan(workflow, None, object(), user_approved=True) is None
    factory.assert_not_called()


def test_user_approval_gate_stops_before_execution():
    workflow, factory, _mode = _workflow()

    result = execute_approved_plan(
        workflow,
        _report(),
        SimpleNamespace(plan_id="plan-1"),
        user_approved=False,
    )

    assert result is None
    factory.assert_not_called()


def test_artifact_mismatch_stops_before_execution():
    workflow, factory, _mode = _workflow()

    result = execute_approved_plan(
        workflow,
        _report(plan_id="plan-a"),
        SimpleNamespace(plan_id="plan-b"),
        user_approved=True,
    )

    assert result is None
    factory.assert_not_called()


def test_all_gates_pass_exact_artifacts_to_execution_mode():
    expected = SimpleNamespace(
        execution_status=ExecutionStatus.SUCCESS,
        steps_succeeded=2,
        total_steps=2,
    )
    workflow, factory, mode = _workflow(expected)
    report = _report()
    plan = SimpleNamespace(plan_id="plan-1")

    result = execute_approved_plan(
        workflow, report, plan, user_approved=True, intent_id="intent-1"
    )

    assert result is expected
    factory.assert_called_once_with()
    mode.execute_plan.assert_called_once_with(
        dry_run_report=report,
        plan_artifact=plan,
        user_approved=True,
        intent_id="intent-1",
    )
