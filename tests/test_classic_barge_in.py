import pytest

from core.classic_barge_in import ClassicBargeInGate


def evaluate(gate, now, **overrides):
    inputs = {
        "is_speaking": True,
        "volume": 22.0,
        "threshold": 6.0,
        "enabled": True,
        "suppressed": False,
    }
    inputs.update(overrides)
    return gate.evaluate(now=now, **inputs)


def test_one_loud_frame_is_held_as_possible_echo():
    decision = evaluate(ClassicBargeInGate(), 10.0)

    assert decision.pending is True
    assert decision.triggered is False
    assert decision.effective_threshold == 21.0


def test_continuous_voice_triggers_only_after_hold_period():
    gate = ClassicBargeInGate()

    assert evaluate(gate, 10.0).pending is True
    assert evaluate(gate, 10.179).triggered is False
    assert evaluate(gate, 10.181).triggered is True


def test_quiet_frame_resets_the_continuous_voice_timer():
    gate = ClassicBargeInGate()

    evaluate(gate, 10.0)
    assert evaluate(gate, 10.10, volume=0.0).pending is False
    assert evaluate(gate, 10.20).pending is True
    assert evaluate(gate, 10.30).triggered is False


@pytest.mark.parametrize(
    ("overrides", "effective_threshold"),
    [
        ({"is_speaking": False}, 6.0),
        ({"enabled": False}, 21.0),
        ({"suppressed": True}, 21.0),
        ({"volume": 20.99}, 21.0),
    ],
)
def test_non_candidates_neither_wait_nor_trigger(overrides, effective_threshold):
    decision = evaluate(ClassicBargeInGate(), 10.0, **overrides)

    assert decision.pending is False
    assert decision.triggered is False
    assert decision.effective_threshold == effective_threshold


def test_invalid_gate_configuration_fails_early():
    with pytest.raises(ValueError, match="hold_seconds"):
        ClassicBargeInGate(hold_seconds=-0.01)
    with pytest.raises(ValueError, match="speaking_multiplier"):
        ClassicBargeInGate(speaking_multiplier=0)
