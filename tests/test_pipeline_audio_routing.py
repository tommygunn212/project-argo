from types import SimpleNamespace

import core.pipeline_audio_routing as routing_module
from core.pipeline_audio_routing import PipelineAudioRoutingService


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


def test_audio_status_format_preserves_device_lists():
    assert PipelineAudioRoutingService.format_status(
        {
            "default_output": "Speakers",
            "default_input": "Microphone",
            "output_devices": ["Speakers", "Headset"],
            "input_devices": ["Microphone"],
        }
    ) == (
        "Audio output is set to Speakers. Input is Microphone. "
        "Available outputs: Speakers, Headset. Available inputs: Microphone."
    )


def test_status_request_cannot_mutate_audio_routing(monkeypatch):
    host = Host()
    service = PipelineAudioRoutingService(host)
    monkeypatch.setattr(
        routing_module,
        "get_audio_routing_status",
        lambda: (_ for _ in ()).throw(AssertionError("status probe must not run")),
    )

    assert service.respond_status("switch to headset", "id", False, None)
    assert host.deliveries[0][0][0].startswith("Audio routing status cannot change")


def test_blocked_control_does_not_call_routing_mutator(monkeypatch):
    host = Host()
    host.gate = (False, "disabled")
    service = PipelineAudioRoutingService(host)
    monkeypatch.setattr(
        routing_module,
        "set_audio_routing",
        lambda *_: (_ for _ in ()).throw(AssertionError("mutation must not run")),
    )

    assert service.respond_control(
        SimpleNamespace(target="Headset"),
        "switch to headset",
        1.0,
        "id",
        False,
        None,
    )
    assert host.deliveries[0][0][0] == "Audio routing control blocked by policy (disabled)."


def test_allowed_input_control_routes_microphone(monkeypatch):
    host = Host()
    service = PipelineAudioRoutingService(host)
    calls = []
    monkeypatch.setattr(
        routing_module,
        "set_audio_routing",
        lambda target, is_input: (calls.append((target, is_input)) or True, "Input changed."),
    )

    assert service.respond_control(
        SimpleNamespace(target="Desk Mic"),
        "set audio input to desk mic",
        1.0,
        "id",
        False,
        None,
    )
    assert calls == [("Desk Mic", True)]
