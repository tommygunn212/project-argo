import queue
from types import SimpleNamespace

import core.coordinator_loop as loop_module
from core.coordinator_loop import run_coordinator_loop


class Flag:
    def is_set(self):
        return False


class Memory:
    capacity = 4

    def __init__(self):
        self.cleared = False

    def clear(self):
        self.cleared = True


class Host:
    MAX_INTERACTIONS = 1
    STOP_KEYWORDS = {"stop"}
    SPEECH_START_POLL_SECONDS = 0.1
    idle_sleep_seconds = 60.0

    def __init__(self):
        self.logs = []
        self.logger = SimpleNamespace(
            info=lambda message: self.logs.append(("info", message)),
            warning=lambda message: self.logs.append(("warning", message)),
            error=lambda message: self.logs.append(("error", message)),
        )
        self.memory = Memory()
        self.latency_stats = SimpleNamespace(log_report=lambda: self.logs.append(("latency", "report")))
        self.state_machine = SimpleNamespace(is_asleep=False, sleep=lambda: True)
        self.stop_requested = False
        self.interaction_count = 0
        self.interaction_id = 1
        self._wake_event_queue = queue.Queue()
        self._last_utterance_time = None
        self._is_speaking = Flag()
        self._is_processing = Flag()
        self.wake_listener_started = False

    def _start_wake_listener(self):
        self.wake_listener_started = True

    def _handle_wake_event(self):
        self.stop_requested = True

    def _safe_transition(self, *args, **kwargs):
        return True

    def _wait_for_speech_start(self, _timeout):
        return [b"audio"]

    def _handle_interaction(self, initial_frames=None, mark_wake=False):
        self.interaction_count += 1
        return True


def test_loop_processes_one_interaction_and_cleans_up(monkeypatch):
    host = Host()
    monkeypatch.setattr(loop_module, "_music_is_playing", lambda: False)

    run_coordinator_loop(host)

    assert host.wake_listener_started
    assert host.interaction_count == 1
    assert host.memory.cleared
    assert ("latency", "report") in host.logs


def test_wake_event_can_stop_before_audio_capture():
    host = Host()
    host._wake_event_queue.put(object())
    host._wait_for_speech_start = lambda *_: (_ for _ in ()).throw(
        AssertionError("capture must not start")
    )

    run_coordinator_loop(host)

    assert host.stop_requested
    assert host.interaction_count == 0
    assert host.memory.cleared


def test_loop_clears_memory_when_interaction_raises():
    host = Host()
    host._handle_interaction = lambda **_: (_ for _ in ()).throw(RuntimeError("boom"))

    try:
        run_coordinator_loop(host)
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected failure")

    assert host.memory.cleared
