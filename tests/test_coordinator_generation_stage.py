from types import SimpleNamespace
from unittest.mock import Mock

from core import coordinator_generation_stage as stage


class FakeWatchdog:
    def __init__(self, triggered=False):
        self.triggered = triggered

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def host():
    return SimpleNamespace(
        logger=Mock(),
        current_probe=Mock(),
        interaction_count=2,
        generator=SimpleNamespace(generate=Mock(return_value="generated")),
        memory=object(),
    )


def test_normal_response_uses_llm_and_marks_timing(monkeypatch):
    coordinator = host()
    intent = object()
    monkeypatch.setattr(stage, "dispatch_music_stage", lambda *args: SimpleNamespace(routed=False))

    result = stage.generate_interaction_response(
        coordinator,
        intent,
        Mock(),
        Mock(),
        watchdog_factory=lambda *args: FakeWatchdog(),
    )

    assert result.response_text == "generated"
    assert result.is_music_iteration is False
    coordinator.generator.generate.assert_called_once_with(intent, coordinator.memory)
    assert coordinator.current_probe.mark.call_args_list == [
        (("llm_start",),),
        (("llm_end",),),
    ]


def test_triggered_llm_watchdog_replaces_response(monkeypatch):
    coordinator = host()
    monkeypatch.setattr(stage, "dispatch_music_stage", lambda *args: SimpleNamespace(routed=False))

    result = stage.generate_interaction_response(
        coordinator,
        object(),
        Mock(),
        Mock(),
        watchdog_factory=lambda *args: FakeWatchdog(triggered=True),
    )

    assert result.response_text == stage.WATCHDOG_FALLBACK_RESPONSE


def test_music_result_is_returned_without_calling_llm(monkeypatch):
    coordinator = host()
    music = SimpleNamespace(
        routed=True,
        response_text="playing",
        output_produced=True,
        is_music_iteration=True,
        return_interaction=True,
        interaction_result=True,
    )
    monkeypatch.setattr(stage, "dispatch_music_stage", lambda *args: music)

    result = stage.generate_interaction_response(coordinator, object(), Mock(), Mock())

    assert result.response_text == "playing"
    assert result.output_produced is True
    assert result.is_music_iteration is True
    assert result.return_interaction is True
    coordinator.generator.generate.assert_not_called()
