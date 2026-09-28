from types import SimpleNamespace

import core.coordinator_system_health_stage as stage
from core.intent_parser import IntentType


class _Recorder:
    def __init__(self):
        self.items = []

    def mark(self, name):
        self.items.append(name)

    def log_summary(self):
        self.items.append("summary")

    def add_probe(self, probe):
        self.items.append(probe)


class _Logger:
    def info(self, *args, **kwargs):
        pass


class _Coordinator:
    def __init__(self):
        self.logger = _Logger()
        self.interaction_count = 3
        self.interaction_id = 17
        self.current_probe = _Recorder()
        self.latency_stats = _Recorder()
        self.spoken = []
        self._last_utterance_time = None

    def _safe_speak(self, text, interaction_id=None):
        self.spoken.append((text, interaction_id))

    def _format_system_health(self, health):
        return f"health:{health['cpu_percent']}"

    def _format_system_full_report(self, report):
        return f"full:{report['status']}"

    def _format_temperature_response(self, temperatures):
        return f"temperature:{temperatures['cpu']}"


def _intent(intent_type=IntentType.SYSTEM_HEALTH, subintent=None, text=""):
    return SimpleNamespace(intent_type=intent_type, subintent=subintent, raw_text=text)


def _dispatch(coordinator, intent):
    callbacks = []
    handled = stage.dispatch_system_health_stage(
        coordinator,
        intent,
        lambda: callbacks.append("output"),
        lambda: callbacks.append("finalized"),
    )
    return handled, callbacks


def test_unrelated_intent_is_not_handled():
    coordinator = _Coordinator()

    handled, callbacks = _dispatch(coordinator, _intent(IntentType.QUESTION))

    assert handled is False
    assert callbacks == []
    assert coordinator.spoken == []


def test_generic_health_query_preserves_probe_and_watchdog_flow(monkeypatch):
    coordinator = _Coordinator()
    monkeypatch.setattr(
        stage,
        "get_system_health",
        lambda: {"cpu_percent": 12, "ram_percent": 34, "disk_percent": 56},
    )

    handled, callbacks = _dispatch(coordinator, _intent(text="system health"))

    assert handled is True
    assert callbacks == ["output", "finalized"]
    assert coordinator.spoken == [("health:12", 17)]
    assert coordinator.current_probe.items == [
        "llm_end",
        "tts_start",
        "tts_end",
        "summary",
    ]
    assert coordinator.latency_stats.items == [coordinator.current_probe]


def test_disk_query_reports_requested_drive(monkeypatch):
    coordinator = _Coordinator()
    monkeypatch.setattr(
        stage,
        "get_disk_info",
        lambda: {"C:": {"percent": 72, "free_gb": 101.5}},
    )

    handled, callbacks = _dispatch(coordinator, _intent(text="how full is c drive"))

    assert handled is True
    assert callbacks == ["output", "finalized"]
    assert coordinator.spoken == [("C drive is 72 percent full, with 101.5 gigabytes free.", 17)]


def test_detailed_memory_query_keeps_early_return_behavior(monkeypatch):
    coordinator = _Coordinator()
    monkeypatch.setattr(
        stage,
        "get_system_profile",
        lambda: {"ram_gb": 64, "memory_speed_mhz": 6000, "memory_modules": 2},
    )
    monkeypatch.setattr(stage, "get_gpu_profile", lambda: [])

    handled, callbacks = _dispatch(
        coordinator,
        _intent(subintent="memory", text="detailed memory specs"),
    )

    assert handled is True
    assert callbacks == ["output", "finalized"]
    assert coordinator.spoken == [("Your system has 64 gigabytes of memory (6000MHz, 2 modules).", 17)]


def test_unavailable_temperature_has_clear_fallback(monkeypatch):
    coordinator = _Coordinator()
    monkeypatch.setattr(
        stage,
        "get_temperature_health",
        lambda: {"error": "TEMPERATURE_UNAVAILABLE"},
    )

    handled, callbacks = _dispatch(
        coordinator,
        _intent(subintent="temperature", text="temperatures"),
    )

    assert handled is True
    assert callbacks == ["output", "finalized"]
    assert coordinator.spoken == [("Temperature sensors are not available on this system.", 17)]
