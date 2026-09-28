from types import SimpleNamespace

import core.pipeline_bluetooth as bluetooth_module
from core.pipeline_bluetooth import BluetoothDependencies, PipelineBluetoothService


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


def service_for(host):
    return PipelineBluetoothService(
        BluetoothDependencies(
            logger=host.logger,
            minimum_confidence=lambda: host._personal_mode_min_confidence,
            deliver_response=host._deliver_canonical_response,
            evaluate_gates=host._evaluate_gates,
        )
    )


def test_status_format_preserves_device_details():
    message = PipelineBluetoothService.format_status(
        {
            "adapter_present": True,
            "adapter_enabled": True,
            "paired_devices": ["Keyboard"],
            "connected_devices": ["Headset"],
            "audio_device_active": True,
        }
    )

    assert message == (
        "Bluetooth is on. Paired devices: 1. Connected devices: Headset. "
        "Audio device active: yes."
    )


def test_status_path_never_executes_a_control_command(monkeypatch):
    host = Host()
    service = service_for(host)
    monkeypatch.setattr(
        bluetooth_module,
        "get_bluetooth_status",
        lambda: (_ for _ in ()).throw(AssertionError("status probe must not run")),
    )

    assert service.respond_status("turn bluetooth off", "id", False, None)
    assert host.deliveries[0][0][0].startswith("Bluetooth status cannot change")


def test_control_path_checks_gate_before_device_mutation(monkeypatch):
    host = Host()
    host.gate = (False, "disabled")
    service = service_for(host)
    monkeypatch.setattr(
        bluetooth_module,
        "set_bluetooth_enabled",
        lambda *_: (_ for _ in ()).throw(AssertionError("mutation must not run")),
    )

    assert service.respond_control(
        SimpleNamespace(action="on", target=None),
        "turn bluetooth on",
        1.0,
        "id",
        False,
        None,
    )
    assert host.deliveries[0][0][0] == "Bluetooth control blocked by policy (disabled)."


def test_control_path_executes_explicit_allowed_action(monkeypatch):
    host = Host()
    service = service_for(host)
    calls = []
    monkeypatch.setattr(
        bluetooth_module,
        "set_bluetooth_enabled",
        lambda enabled: (calls.append(enabled) or True, "Bluetooth enabled."),
    )

    assert service.respond_control(
        SimpleNamespace(action="on", target=None),
        "turn bluetooth on",
        1.0,
        "id",
        False,
        None,
    )
    assert calls == [True]
    assert host.deliveries[0][0][0] == "Bluetooth enabled."
