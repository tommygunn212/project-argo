from types import SimpleNamespace

import pytest

from core.intent_parser import IntentType
from core.pipeline_system_info import dispatch_system_info


class FakePipeline:
    def __init__(self, gate=(True, "allowed")):
        self.gate = gate
        self.stop_signal = SimpleNamespace(is_set=lambda: False)
        self.logs = []
        self.logger = SimpleNamespace(info=lambda *args, **kwargs: self.logs.append(args))
        self.broadcasts = []
        self.spoken = []
        self.transitions = []
        self.timeline = []

    def _evaluate_gates(self, *args):
        self.gate_args = args
        return self.gate

    def broadcast(self, *args):
        self.broadcasts.append(args)

    def _sanitize_tts_text(self, text):
        return text

    def speak(self, text, **kwargs):
        self.spoken.append((text, kwargs))

    def transition_state(self, *args, **kwargs):
        self.transitions.append((args, kwargs))

    def _record_timeline(self, *args, **kwargs):
        self.timeline.append((args, kwargs))


@pytest.mark.parametrize("intent", [None, SimpleNamespace(intent_type=IntentType.MUSIC)])
def test_non_system_info_intents_fall_through(intent):
    pipeline = FakePipeline()

    assert dispatch_system_info(pipeline, intent, "interaction-1", False, None) is False
    assert pipeline.broadcasts == []


@pytest.mark.parametrize(
    ("subintent", "expected"),
    [
        ("memory", "Your system has 32 gigabytes of memory."),
        ("cpu", "Your CPU is a Test CPU."),
        ("gpu", "Your GPU is Test GPU."),
        ("os", "You are running Test OS."),
        ("motherboard", "Your motherboard is Test Board."),
        (None, "Hardware information unavailable."),
    ],
)
def test_each_system_information_shape(monkeypatch, subintent, expected):
    pipeline = FakePipeline()
    parsed_intent = SimpleNamespace(intent_type=IntentType.SYSTEM_INFO, subintent=subintent)
    monkeypatch.setattr(
        "core.pipeline_system_info.get_system_profile",
        lambda: {
            "ram_gb": 32,
            "cpu": "Test CPU",
            "os": "Test OS",
            "motherboard": "Test Board",
        },
    )
    monkeypatch.setattr(
        "core.pipeline_system_info.get_gpu_profile", lambda: [{"name": "Test GPU"}]
    )

    assert dispatch_system_info(
        pipeline, parsed_intent, "interaction-1", False, None
    ) is True
    assert pipeline.gate_args == ("system_health", "system_health", "interaction-1")
    assert pipeline.broadcasts[-1] == ("log", f"Argo: {expected}")
    assert pipeline.spoken[-1][0] == expected
    assert pipeline.transitions[-1][0] == ("LISTENING",)
    assert pipeline.timeline[-1][0] == ("INTERACTION_END",)


def test_policy_block_avoids_hardware_probe(monkeypatch):
    pipeline = FakePipeline(gate=(False, "locked"))
    parsed_intent = SimpleNamespace(intent_type=IntentType.SYSTEM_INFO, subintent="cpu")
    monkeypatch.setattr(
        "core.pipeline_system_info.get_system_profile",
        lambda: pytest.fail("blocked request must not probe hardware"),
    )

    assert dispatch_system_info(
        pipeline, parsed_intent, "interaction-1", False, None
    ) is True
    assert pipeline.broadcasts[-1] == (
        "log",
        "Argo: System information access blocked by policy (locked).",
    )
