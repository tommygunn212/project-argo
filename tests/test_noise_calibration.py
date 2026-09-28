import numpy as np

from core.noise_calibration import calibrate_ambient_noise


class _Logger:
    def __init__(self):
        self.info_messages = []
        self.warning_messages = []

    def info(self, message, *args):
        self.info_messages.append(message % args if args else message)

    def warning(self, message, *args):
        self.warning_messages.append(message % args if args else message)


class _Audio:
    def __init__(self, frames, running=True):
        self.frames = list(frames)
        self.running = running

    def read_frame(self, timeout=None):
        return self.frames.pop(0) if self.frames else None


def _calibrate(audio, **overrides):
    broadcasts = []
    logger = _Logger()
    options = {
        "server_enabled": True,
        "current_vad_threshold": 5.0,
        "current_barge_in_threshold": 6.0,
        "config_vad_threshold": 5.0,
        "calibration_max_multiple": 3.0,
        "input_sample_rate": 100,
        "block_size": 10,
        "broadcast": lambda kind, payload: broadcasts.append((kind, payload)),
        "logger": logger,
        "duration_seconds": 0.2,
    }
    options.update(overrides)
    result = calibrate_ambient_noise(audio, **options)
    return result, broadcasts, logger


def test_stopped_audio_keeps_current_thresholds():
    result, broadcasts, logger = _calibrate(_Audio([], running=False))

    assert result.vad_threshold == 5.0
    assert result.barge_in_threshold == 6.0
    assert result.calibrated is False
    assert broadcasts == [("log", "Calibration skipped — start listening first")]
    assert logger.warning_messages


def test_missing_frames_falls_back_to_config_threshold():
    result, broadcasts, _logger = _calibrate(
        _Audio([]),
        current_vad_threshold=7.0,
        current_barge_in_threshold=8.4,
    )

    assert result.vad_threshold == 5.0
    assert result.barge_in_threshold == 8.4
    assert result.calibrated is False
    assert broadcasts[-1] == ("log", "Calibration failed — no audio frames")


def test_quiet_calibration_respects_configured_minimum():
    frames = [np.array([0.01], dtype=np.float32)] * 2

    result, broadcasts, _logger = _calibrate(_Audio(frames))

    assert result.vad_threshold == 5.0
    assert result.barge_in_threshold == 6.0
    assert result.calibrated is True
    assert broadcasts[-1][0] == "noise_calibration"


def test_noisy_calibration_is_clamped_to_ceiling():
    frames = [np.array([10.0], dtype=np.float32)] * 2

    result, broadcasts, logger = _calibrate(_Audio(frames))

    assert result.vad_threshold == 15.0
    assert result.barge_in_threshold == 18.0
    assert any("threshold clamped" in payload for kind, payload in broadcasts if kind == "log")
    assert any("above the ceiling" in message for message in logger.warning_messages)
