"""Characterization tests for the public dry-run confirmation gate."""

from types import SimpleNamespace

import wrapper.argo as argo


class _Engine:
    def __init__(self, report):
        self.report = report
        self.calls = []

    def dry_run(self, **kwargs):
        self.calls.append(kwargs)
        return self.report


def _plan():
    return SimpleNamespace(
        intent_id="intent-1",
        transcription_id="transcription-1",
    )


def _report(*, feasible=True, risk="safe"):
    return SimpleNamespace(
        summary=lambda: "simulation summary",
        highest_risk_detected=risk,
        execution_feasible=feasible,
        blocking_reason=None if feasible else "missing prerequisite",
        user_approved_execution=None,
    )


def test_dry_run_rejects_when_engine_is_unavailable(monkeypatch, capsys):
    monkeypatch.setattr(argo, "EXECUTION_ENGINE_AVAILABLE", False)

    approved, report = argo.dry_run_and_confirm(_plan())

    assert approved is False
    assert report is None
    assert "not available" in capsys.readouterr().err


def test_dry_run_infeasible_report_never_prompts(monkeypatch):
    report = _report(feasible=False)
    engine = _Engine(report)
    monkeypatch.setattr(argo, "EXECUTION_ENGINE_AVAILABLE", True)
    monkeypatch.setattr(argo, "ExecutionEngine", lambda: engine)
    monkeypatch.setattr(
        "builtins.input",
        lambda: (_ for _ in ()).throw(AssertionError("must not prompt")),
    )

    approved, returned = argo.dry_run_and_confirm(_plan())

    assert approved is False
    assert returned is report
    assert report.user_approved_execution is None


def test_dry_run_records_explicit_approval(monkeypatch):
    report = _report(risk="safe")
    engine = _Engine(report)
    plan = _plan()
    monkeypatch.setattr(argo, "EXECUTION_ENGINE_AVAILABLE", True)
    monkeypatch.setattr(argo, "ExecutionEngine", lambda: engine)
    monkeypatch.setattr("builtins.input", lambda: "YES")

    approved, returned = argo.dry_run_and_confirm(plan)

    assert approved is True
    assert returned is report
    assert report.user_approved_execution is True
    assert engine.calls == [
        {
            "plan": plan,
            "intent_id": "intent-1",
            "transcription_id": "transcription-1",
        }
    ]


def test_dry_run_records_rejection(monkeypatch):
    report = _report(risk="risky")
    engine = _Engine(report)
    monkeypatch.setattr(argo, "EXECUTION_ENGINE_AVAILABLE", True)
    monkeypatch.setattr(argo, "ExecutionEngine", lambda: engine)
    monkeypatch.setattr("builtins.input", lambda: "no")

    approved, returned = argo.dry_run_and_confirm(_plan())

    assert approved is False
    assert returned is report
    assert report.user_approved_execution is False
