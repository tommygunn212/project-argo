from types import SimpleNamespace
from unittest.mock import Mock

from core.coordinator_response_guard import CoordinatorResponseGuard


class FakeWatchdog:
    def __init__(self, triggered=False):
        self.triggered = triggered
        self.elapsed_seconds = 3.5
        self.entered = 0
        self.exited = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *args):
        self.exited += 1


def build_guard(*, triggered=False, fallback="fallback"):
    watchdog = FakeWatchdog(triggered)
    host = SimpleNamespace(
        logger=Mock(),
        stop_requested=True,
        _is_speaking=Mock(),
        _safe_speak=Mock(),
    )
    guard = CoordinatorResponseGuard(
        host,
        watchdog_factory=lambda *args: watchdog,
        fallback_response=fallback,
    )
    return guard, host, watchdog


def test_finalize_closes_watchdog_exactly_once():
    guard, _, watchdog = build_guard()

    guard.finalize()
    guard.finalize()

    assert watchdog.entered == 1
    assert watchdog.exited == 1


def test_triggered_watchdog_speaks_fallback_and_restores_safe_state():
    guard, host, _ = build_guard(triggered=True)

    guard.finalize()

    host._safe_speak.assert_called_once_with("fallback")
    host._is_speaking.clear.assert_called_once_with()
    assert host.stop_requested is False
    assert guard.output_produced is True


def test_existing_output_suppresses_watchdog_fallback():
    guard, host, _ = build_guard(triggered=True)
    guard.mark_output()

    guard.finalize()

    host._safe_speak.assert_not_called()
    host._is_speaking.clear.assert_not_called()


def test_empty_fallback_still_restores_safe_state():
    guard, host, _ = build_guard(triggered=True, fallback="")

    guard.finalize()

    host._safe_speak.assert_not_called()
    host._is_speaking.clear.assert_called_once_with()
    assert guard.output_produced is False
