from types import SimpleNamespace

import core.pipeline_system_volume as volume_module
from core.pipeline_system_volume import PipelineSystemVolumeService


class Host:
    def __init__(self):
        self.logger = SimpleNamespace(info=lambda *_: None)
        self.deliveries = []
        self.gate = (True, "allowed")

    def _deliver_canonical_response(self, *args, **kwargs):
        self.deliveries.append((args, kwargs))
        return True

    def _evaluate_gates(self, *args):
        return self.gate


def test_system_volume_scope_excludes_music_apps_and_devices():
    classify = PipelineSystemVolumeService.is_system_volume_text

    assert classify("set volume to 25")
    assert classify("mute")
    assert not classify("turn music volume down")
    assert not classify("set app volume to 25")
    assert not classify("use the headphones")


def test_status_gate_runs_before_volume_probe(monkeypatch):
    host = Host()
    host.gate = (False, "disabled")
    service = PipelineSystemVolumeService(host)
    monkeypatch.setattr(
        volume_module,
        "get_status",
        lambda: (_ for _ in ()).throw(AssertionError("probe must not run")),
    )

    assert service.respond_status("id", False, None)
    assert host.deliveries[0][0][0] == "System volume status blocked by policy (disabled)."


def test_control_gate_runs_before_volume_mutation(monkeypatch):
    host = Host()
    host.gate = (False, "disabled")
    service = PipelineSystemVolumeService(host)
    monkeypatch.setattr(
        volume_module,
        "set_volume_percent",
        lambda *_: (_ for _ in ()).throw(AssertionError("mutation must not run")),
    )

    assert service.respond_control("set volume to 25", "id", False, None)
    assert host.deliveries[0][0][0] == "System volume control blocked by policy (disabled)."


def test_explicit_percentage_control_preserves_result(monkeypatch):
    host = Host()
    service = PipelineSystemVolumeService(host)
    calls = []
    monkeypatch.setattr(volume_module, "get_status", lambda: (70, False))
    monkeypatch.setattr(
        volume_module,
        "set_volume_percent",
        lambda value: (calls.append(value) or True, "ok", 70, value, False),
    )

    assert service.respond_control("set volume to 25%", "id", False, None)
    assert calls == [25]
    assert host.deliveries[0][0][0] == "System volume set to 25%."
