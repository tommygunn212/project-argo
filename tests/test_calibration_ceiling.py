"""Calibration must not be able to deafen ARGO.

calibrate_noise_floor raises the wake threshold to 1.5x the p95 of whatever
the mic heard in a 2 second window. If anything was PLAYING in that window -
music, ARGO's own TTS, a test run - that p95 is not ambient noise, and the
threshold lands above anything a voice reaches. ARGO then ignores speech
until someone restarts it, with nothing in the log that looks like a fault.

Measured on bigdog: quiet room -> 0.200. Restarted while the test suite was
playing TTS -> 0.183 floor, threshold 1.272, completely deaf.
"""

import numpy as np
import pytest


CONFIG_THRESHOLD = 0.2
MAX_MULTIPLE = 3.0


def adaptive(rms_samples, multiplier=2.5, config_threshold=CONFIG_THRESHOLD,
             max_multiple=MAX_MULTIPLE):
    """The threshold calculation from main.calibrate_noise_floor."""
    noise_floor = float(np.mean(rms_samples))
    noise_peak = float(np.percentile(rms_samples, 95))
    value = max(noise_peak * 1.5, noise_floor * multiplier)
    value = max(value, config_threshold)
    return min(value, config_threshold * max_multiple)


def test_quiet_room_lands_on_the_configured_floor():
    """mean 0.009, p95 0.024 - the real measurement from a quiet startup."""
    samples = list(np.random.default_rng(0).normal(0.009, 0.005, 200).clip(0, None))
    assert adaptive(samples) == pytest.approx(CONFIG_THRESHOLD)


def test_calibrating_against_playing_audio_is_clamped():
    """mean 0.183, p95 0.848 - the real measurement that made ARGO deaf.
    Uncapped this is 1.272."""
    samples = [0.12] * 90 + [0.848] * 10  # p95 lands on the loud tail: 0.848
    uncapped = max(np.percentile(samples, 95) * 1.5, np.mean(samples) * 2.5)

    assert uncapped > 1.0, "premise: the raw calculation is unreachable"
    assert adaptive(samples) <= CONFIG_THRESHOLD * MAX_MULTIPLE


def test_the_ceiling_is_always_reachable_by_a_voice():
    """Whatever the room does, the threshold stays in the range speech can
    actually produce. A threshold above 1.0 is deafness, not sensitivity."""
    absurd = [5.0] * 100
    assert adaptive(absurd) < 1.0


def test_a_genuinely_noisy_room_still_raises_the_threshold():
    """The cap must not flatten real adaptation - a noisy room should sit
    above a quiet one, just not out of reach."""
    quiet = list(np.random.default_rng(1).normal(0.009, 0.005, 200).clip(0, None))
    noisy = list(np.random.default_rng(2).normal(0.12, 0.02, 200).clip(0, None))

    assert adaptive(noisy) > adaptive(quiet)


def test_the_ceiling_is_wired_into_main():
    """The constant has to exist where calibration runs, not just here."""
    import inspect

    import main

    source = inspect.getsource(main.main_loop)
    assert "CALIBRATION_MAX_MULTIPLE" in source
    assert "ceiling" in source
