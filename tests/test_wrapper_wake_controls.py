import logging

import pytest

from wrapper.wake_controls import (
    detector_status,
    pause_detector,
    resume_detector,
    start_detector,
    stop_detector,
)


class FakeDetector:
    def __init__(self):
        self.calls = []

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")

    def pause(self):
        self.calls.append("pause")

    def resume(self):
        self.calls.append("resume")

    def get_status(self):
        return {"available": True}


def test_wake_controls_delegate_to_detector():
    detector = FakeDetector()
    logger = logging.getLogger()

    start_detector(detector, logger)
    pause_detector(detector, logger)
    resume_detector(detector, logger)
    stop_detector(detector, logger)

    assert detector.calls == ["start", "pause", "resume", "stop"]
    assert detector_status(detector) == {"available": True}
    assert detector_status(None) == {"available": False}


@pytest.mark.parametrize(
    "operation", [start_detector, stop_detector, pause_detector, resume_detector]
)
def test_wake_controls_log_and_swallow_detector_errors(operation, caplog):
    class BrokenDetector:
        def __getattr__(self, name):
            return lambda: (_ for _ in ()).throw(RuntimeError("broken"))

    with caplog.at_level(logging.ERROR):
        operation(BrokenDetector(), logging.getLogger("test.wake"))

    assert "broken" in caplog.text
