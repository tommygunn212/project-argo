"""Symbolic execution and explicit approval workflow for wrapper plans."""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Any, Callable


@dataclass(frozen=True)
class DryRunWorkflow:
    engine_available: bool
    engine_factory: Callable[[], Any] | None
    read_confirmation: Callable[[], str]


def simulate_with_confirmation(
    workflow: DryRunWorkflow,
    plan_artifact: Any,
) -> tuple[bool, Any | None]:
    """Simulate a plan without side effects and require explicit approval."""
    if not workflow.engine_available or workflow.engine_factory is None:
        print("⚠ Execution engine (v1.3.0) not available.", file=sys.stderr)
        return False, None

    report = workflow.engine_factory().dry_run(
        plan=plan_artifact,
        intent_id=getattr(plan_artifact, "intent_id", None),
        transcription_id=getattr(plan_artifact, "transcription_id", None),
    )

    print(f"\n{'=' * 70}", file=sys.stderr)
    print("DRY-RUN SIMULATION RESULTS", file=sys.stderr)
    print(f"{'=' * 70}", file=sys.stderr)
    print(f"\n{report.summary()}", file=sys.stderr)
    print(f"\n{'=' * 70}", file=sys.stderr)

    if report.highest_risk_detected == "critical":
        print("🚨 CRITICAL RISK: This plan has irreversible actions.", file=sys.stderr)
        print(
            "   Proceed only if you understand the consequences.", file=sys.stderr
        )
    elif report.highest_risk_detected == "risky":
        print("⚠️  RISKY: Partial rollback available if execution fails.", file=sys.stderr)
    elif report.highest_risk_detected == "cautious":
        print(
            "ℹ️  CAUTION: Plan is fully reversible but changes system state.",
            file=sys.stderr,
        )

    if not report.execution_feasible:
        print(
            f"\n❌ EXECUTION NOT FEASIBLE: {report.blocking_reason}",
            file=sys.stderr,
        )
        print(
            "   Simulation indicates this plan cannot be executed safely.",
            file=sys.stderr,
        )
        return False, report

    print(f"\n{'=' * 70}", file=sys.stderr)
    if report.highest_risk_detected == "safe":
        print("Approve execution of this plan? (yes/no): ", end="", file=sys.stderr)
    else:
        print(
            f"⚠️  Execute despite {report.highest_risk_detected} risk? (yes/no): ",
            end="",
            file=sys.stderr,
        )
    sys.stderr.flush()

    try:
        response = workflow.read_confirmation().strip().lower()
    except EOFError:
        response = "no"
    if response in ("yes", "y", "yep", "yeah", "ok", "sure"):
        report.user_approved_execution = True
        print(
            "✅ Execution approved. Ready for real execution (v1.4.0+).\n",
            file=sys.stderr,
        )
        return True, report

    report.user_approved_execution = False
    print("❌ Execution rejected. Plan will not be executed.\n", file=sys.stderr)
    return False, report
