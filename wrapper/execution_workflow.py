"""Hard-gated real execution workflow for wrapper plans."""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Any, Callable


@dataclass(frozen=True)
class ExecutionWorkflow:
    engine_available: bool
    execution_mode_factory: Callable[[], Any] | None
    simulation_status: Any
    execution_status: Any


def execute_approved_plan(
    workflow: ExecutionWorkflow,
    dry_run_report: Any,
    plan_artifact: Any,
    *,
    user_approved: bool = False,
    intent_id: str = "",
) -> Any | None:
    """Validate all hard gates before allowing a real execution call."""
    if not workflow.engine_available or workflow.execution_mode_factory is None:
        print("❌ Execution engine not available. Cannot execute plan.", file=sys.stderr)
        return None
    if dry_run_report is None:
        print(
            "❌ GATE 1 FAILED: No dry-run report provided. Execution aborted.",
            file=sys.stderr,
        )
        print(
            "   Simulation must complete successfully before execution.",
            file=sys.stderr,
        )
        return None
    if dry_run_report.simulation_status != workflow.simulation_status.SUCCESS:
        print(
            f"❌ GATE 2 FAILED: Simulation status is "
            f"{dry_run_report.simulation_status.value}.",
            file=sys.stderr,
        )
        print("   Only SUCCESS simulations can be executed.", file=sys.stderr)
        if dry_run_report.blocking_reason:
            print(f"   Reason: {dry_run_report.blocking_reason}", file=sys.stderr)
        return None
    if not user_approved:
        print(
            "❌ GATE 3 FAILED: User has not approved execution.", file=sys.stderr
        )
        print("   Execution requires explicit confirmation.", file=sys.stderr)
        return None
    if dry_run_report.execution_plan_id != plan_artifact.plan_id:
        print("❌ GATES 4-5 FAILED: Artifact ID mismatch.", file=sys.stderr)
        print(
            f"   Report plan ID: {dry_run_report.execution_plan_id}", file=sys.stderr
        )
        print(f"   Artifact plan ID: {plan_artifact.plan_id}", file=sys.stderr)
        print(
            "   Execution aborted to prevent mismatched execution.", file=sys.stderr
        )
        return None

    print("\n" + "=" * 70, file=sys.stderr)
    print("ALL HARD GATES PASSED - EXECUTING PLAN", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    result = workflow.execution_mode_factory().execute_plan(
        dry_run_report=dry_run_report,
        plan_artifact=plan_artifact,
        user_approved=user_approved,
        intent_id=intent_id,
    )
    if result.execution_status == workflow.execution_status.SUCCESS:
        print("\n✅ EXECUTION SUCCESSFUL", file=sys.stderr)
        print(
            f"   {result.steps_succeeded}/{result.total_steps} steps completed",
            file=sys.stderr,
        )
    elif result.execution_status == workflow.execution_status.PARTIAL:
        print("\n⚠️  EXECUTION PARTIAL", file=sys.stderr)
        print(
            f"   {result.steps_succeeded}/{result.total_steps} steps succeeded",
            file=sys.stderr,
        )
        print(
            f"   {result.steps_failed}/{result.total_steps} steps failed",
            file=sys.stderr,
        )
    elif result.execution_status == workflow.execution_status.ROLLED_BACK:
        print("\n⚠️  EXECUTION ROLLED BACK", file=sys.stderr)
        print("   System state restored due to step failure", file=sys.stderr)
    elif result.execution_status == workflow.execution_status.ABORTED:
        print("\n❌ EXECUTION ABORTED", file=sys.stderr)
        print(f"   Reason: {result.abort_reason}", file=sys.stderr)
    return result
