"""Speech detection on the classic path.

Two defects lived here. Silence was decided by comparing a NORMALIZED rms
(0-1) against SILENCE_THRESHOLD = 250, an absolute int16 level - always
true, so the silence timer ran from the first sample of speech and cut
the recording off ~2.2s in whether or not Tommy was still talking. And
"is this speech" was a bare energy test at 0.0005 normalized, which a fan
or a keystroke clears comfortably.
"""

import numpy as np
import pytest

from core.vad_silero import SileroGate, _to_float32

SR = 16000


def _chunk(kind: str, n: int = 1600) -> np.ndarray:
    if kind == "silence":
        return np.zeros(n, dtype=np.int16)
    if kind == "noise":
        rng = np.random.default_rng(0)
        return (rng.normal(0, 0.15, n) * 32767).clip(-32768, 32767).astype(np.int16)
    if kind == "tone":
        t = np.arange(n) / SR
        return (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    raise ValueError(kind)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.astype(float) ** 2)) / 32768.0)


@pytest.fixture(scope="module")
def gate():
    g = SileroGate(sample_rate=SR)
    if not g.available:
        pytest.skip("Silero ONNX model not loadable in this environment")
    return g


# --- the threshold-scale bug ----------------------------------------------

def test_silence_threshold_is_on_the_same_scale_as_the_rms_it_compares():
    """SILENCE_THRESHOLD was 250 while rms is normalized 0-1."""
    from core.coordinator import Coordinator as C

    assert 0.0 < C.SILENCE_THRESHOLD < 1.0
    assert C.SILENCE_THRESHOLD > C.RMS_SPEECH_THRESHOLD, (
        "the silence floor must sit above the speech floor, or every chunk "
        "counts as both"
    )


def test_silence_floor_clears_this_room_s_measured_noise():
    """Startup calibration on bigdog reports mean=0.009, p95=0.024 ambient.
    A floor under that never sees silence, so recording runs to the 15s cap -
    the exact mirror of the bug this replaced."""
    from core.coordinator import Coordinator as C

    assert C.SILENCE_THRESHOLD > 0.024


def test_loud_speech_level_audio_is_not_called_silence():
    """With the old value of 250, this assertion could never fail - which is
    exactly why the bug survived."""
    from core.coordinator import Coordinator as C

    assert _rms(_chunk("noise")) > C.SILENCE_THRESHOLD


# --- Silero actually discriminates ----------------------------------------

def test_energy_alone_would_call_noise_speech():
    """Establishes the premise: these chunks are loud."""
    from core.coordinator import Coordinator as C

    for kind in ("noise", "tone"):
        assert _rms(_chunk(kind)) > C.RMS_SPEECH_THRESHOLD


@pytest.mark.parametrize("kind", ["silence", "noise", "tone"])
def test_silero_rejects_loud_non_speech(gate, kind):
    gate.reset()
    scores = [gate.probability(_chunk(kind)) for _ in range(10)]
    assert max(scores) < 0.5, f"{kind} was scored as speech"


def test_is_speech_agrees_with_the_threshold(gate):
    gate.reset()
    assert gate.is_speech(_chunk("silence")) is False


# --- degradation ----------------------------------------------------------

def test_unavailable_gate_says_it_cannot_judge_rather_than_saying_silence():
    g = SileroGate(sample_rate=44100)  # unsupported rate, so no model
    assert g.available is False
    assert g.probability(_chunk("noise")) is None
    assert g.is_speech(_chunk("noise")) is None


def test_inference_failure_disables_the_gate_instead_of_raising(gate, monkeypatch):
    g = SileroGate(sample_rate=SR)
    if not g.available:
        pytest.skip("Silero not loadable")

    def boom(_x):
        raise RuntimeError("onnx exploded")

    monkeypatch.setattr(g, "_model", boom)
    assert g.probability(_chunk("noise")) is None
    assert g.available is False


# --- input handling -------------------------------------------------------

def test_int16_is_scaled_and_stereo_is_mixed_down():
    mono = _to_float32(np.array([32767, -32768], dtype=np.int16))
    assert mono[0] == pytest.approx(1.0, abs=1e-3)
    assert mono[1] == pytest.approx(-1.0, abs=1e-3)

    stereo = np.array([[100, 300], [0, 0]], dtype=np.int16)
    assert _to_float32(stereo).shape == (2,)


def test_windows_stay_aligned_across_chunk_boundaries(gate):
    """A 100 ms chunk is 1600 samples; the window is 512. The 64-sample
    remainder must carry into the next chunk, not be dropped."""
    gate.reset()
    gate.probability(_chunk("silence"))
    assert gate._residual.size == 1600 % 512
