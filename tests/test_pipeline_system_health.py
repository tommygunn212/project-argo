from types import SimpleNamespace

import core.pipeline_system_health as stage
from core.intent_parser import IntentType


class _Logger:
    def info(self, *args, **kwargs):
        pass


class _Pipeline:
    def __init__(self, gate=(True, "allowed")):
        self.gate = gate
        self.deliveries = []
        self.logger = _Logger()

    def _evaluate_gates(self, *args):
        return self.gate

    def _deliver_canonical_response(self, message, *args, **kwargs):
        self.deliveries.append((message, args, kwargs))
        return True

    def _format_system_health(self, health):
        return f"health:{health['cpu_percent']}"

    def _format_system_full_report(self, report):
        return f"full:{report['status']}"

    def _format_subsystem_summary(self):
        return "subsystems"

    def _format_gate_summary(self, *args):
        return "gates"

    def _format_governance_summary(self):
        return "governance"

    def _format_temperature_response(self, temperatures):
        return f"temperature:{temperatures['cpu']}"

    def _format_ports_summary(self, ports):
        return f"ports:{ports}"

    def _format_irq_summary(self, irqs):
        return f"irqs:{irqs}"


def _intent(intent_type=IntentType.SYSTEM_HEALTH, subintent=None, text=""):
    return SimpleNamespace(intent_type=intent_type, subintent=subintent, raw_text=text)


def _respond(pipeline, intent, text=""):
    return stage.respond_with_system_health(
        pipeline, text, intent, "interaction-1", False, {"voice": "test"}
    )


def test_policy_block_is_delivered_without_hardware_probe(monkeypatch):
    pipeline = _Pipeline(gate=(False, "disabled"))
    monkeypatch.setattr(stage, "get_system_health", lambda: (_ for _ in ()).throw(AssertionError()))

    assert _respond(pipeline, _intent()) is True
    assert pipeline.deliveries[0][0] == "System health access blocked by policy (disabled)."


def test_system_status_forces_full_report_and_tts(monkeypatch):
    pipeline = _Pipeline(gate=(False, "ignored for status"))
    monkeypatch.setattr(stage, "get_system_full_report", lambda: {"status": "ok"})

    assert _respond(pipeline, _intent(IntentType.SYSTEM_STATUS, text="status")) is True
    message, _, options = pipeline.deliveries[0]
    assert message == "full:ok subsystems gates"
    assert options["enforce_confidence"] is False
    assert options["force_tts"] is True
    assert options["suppress_barge_in_seconds"] == 1.5


def test_requested_drive_is_reported(monkeypatch):
    pipeline = _Pipeline()
    monkeypatch.setattr(stage, "get_disk_info", lambda: {"D:": {"percent": 81, "free_gb": 22.5}})

    assert _respond(pipeline, _intent(text="how full is d drive")) is True
    assert pipeline.deliveries[0][0] == "D drive is 81 percent full, with 22.5 gigabytes free."


def test_detailed_hardware_includes_requested_ports_and_irqs(monkeypatch):
    pipeline = _Pipeline()
    monkeypatch.setattr(
        stage,
        "get_system_profile",
        lambda: {"cpu": "Test CPU", "ram_gb": 32, "ports": ["USB"], "irqs": [7]},
    )
    monkeypatch.setattr(stage, "get_gpu_profile", lambda: [{"name": "Test GPU"}])

    assert _respond(
        pipeline,
        _intent(subintent="hardware", text="hardware ports and irq details"),
    ) is True
    assert pipeline.deliveries[0][0] == (
        "Your CPU is a Test CPU. You have 32 gigabytes of memory. "
        "Your GPU is Test GPU. ports:['USB'] irqs:[7]"
    )


def test_unavailable_temperature_has_clear_fallback(monkeypatch):
    pipeline = _Pipeline()
    monkeypatch.setattr(stage, "get_temperature_health", lambda: {"error": "TEMPERATURE_UNAVAILABLE"})

    assert _respond(pipeline, _intent(subintent="temperature", text="temperature")) is True
    assert pipeline.deliveries[0][0] == "Temperature sensors are not available on this system."
