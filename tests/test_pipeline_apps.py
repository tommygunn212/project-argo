from types import SimpleNamespace

import core.pipeline_apps as apps_module
from core.pipeline_apps import PipelineAppService


class Host:
    def __init__(self):
        self.logger = SimpleNamespace(info=lambda *_: None, error=lambda *_: None)
        self._personal_mode_min_confidence = 0.5
        self.deliveries = []
        self.gate = (True, "allowed")

    def _deliver_canonical_response(self, *args, **kwargs):
        self.deliveries.append((args, kwargs))
        return True

    def _evaluate_gates(self, *args):
        return self.gate


def test_status_path_rejects_control_without_querying_apps(monkeypatch):
    host = Host()
    service = PipelineAppService(host)
    monkeypatch.setattr(
        apps_module,
        "app_status_response",
        lambda *_: (_ for _ in ()).throw(AssertionError("status probe must not run")),
    )

    assert service.respond_status("open notepad", "id", False, None)
    assert host.deliveries[0][0][0].startswith("App status cannot change")


def test_blocked_open_does_not_launch_app(monkeypatch):
    host = Host()
    host.gate = (False, "disabled")
    service = PipelineAppService(host)
    monkeypatch.setattr(apps_module, "resolve_app_name", lambda *_: "notepad")
    monkeypatch.setattr(
        apps_module,
        "open_app",
        lambda *_: (_ for _ in ()).throw(AssertionError("launch must not run")),
    )

    assert service.respond_control(
        SimpleNamespace(action="open"), "open notepad", 1.0, "id", False, None
    )
    assert host.deliveries[0][0][0] == "App control blocked by policy (disabled)."


def test_close_preserves_existing_direct_deterministic_path(monkeypatch):
    host = Host()
    host.gate = (False, "must not be consulted")
    host._evaluate_gates = lambda *_: (_ for _ in ()).throw(
        AssertionError("close path must not consult open gate")
    )
    service = PipelineAppService(host)
    monkeypatch.setattr(apps_module, "resolve_app_name", lambda *_: "notepad")
    monkeypatch.setattr(
        apps_module,
        "close_app_deterministic",
        lambda *_: (True, "Closed Notepad.", 123, "closed"),
    )

    assert service.respond_control(
        SimpleNamespace(action="close"), "close notepad", 0.0, "id", False, None
    )
    assert host.deliveries[0][0][0] == "Closed Notepad."


def test_focus_gate_runs_before_focus_mutation(monkeypatch):
    host = Host()
    host.gate = (False, "disabled")
    service = PipelineAppService(host)
    monkeypatch.setattr(
        apps_module,
        "focus_app_deterministic",
        lambda *_: (_ for _ in ()).throw(AssertionError("focus must not run")),
    )

    assert service.respond_focus_control(
        SimpleNamespace(target="notepad"), "id", False, None
    )
    assert host.deliveries[0][0][0] == "App focus blocked by policy (disabled)."
