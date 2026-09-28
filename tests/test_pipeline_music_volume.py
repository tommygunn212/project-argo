from types import SimpleNamespace

import pytest

from core.pipeline_music_volume import dispatch_music_volume


class FakePipeline:
    def __init__(self, *, executable=True, gate=(True, "allowed")):
        self.executable = executable
        self.gate = gate
        self.stop_signal = SimpleNamespace(is_set=lambda: False)
        self.logger = SimpleNamespace(info=lambda *args, **kwargs: self.logs.append(args))
        self.logs = []
        self.broadcasts = []
        self.spoken = []
        self.transitions = []
        self.timeline = []

    def broadcast(self, *args):
        self.broadcasts.append(args)

    def _sanitize_tts_text(self, text):
        return text

    def speak(self, text, **kwargs):
        self.spoken.append((text, kwargs))

    def transition_state(self, *args, **kwargs):
        self.transitions.append((args, kwargs))

    def _record_timeline(self, *args, **kwargs):
        self.timeline.append((args, kwargs))

    def _is_executable_command(self, _text):
        return self.executable

    def _evaluate_gates(self, *args):
        self.gate_args = args
        return self.gate


@pytest.fixture
def volume(monkeypatch):
    state = {"value": 40, "adjustments": [], "sets": []}

    def set_volume(value):
        state["sets"].append(value)
        state["value"] = value

    def adjust_volume(value):
        state["adjustments"].append(value)
        state["value"] += value

    monkeypatch.setattr("core.music_player.set_volume_percent", set_volume)
    monkeypatch.setattr("core.music_player.adjust_volume_percent", adjust_volume)
    monkeypatch.setattr("core.music_player.get_volume_percent", lambda: state["value"])
    return state


def call(pipeline, text, *, kind="ACTION", low_confidence=False, overrides=None):
    return dispatch_music_volume(
        pipeline, text, kind, low_confidence, "interaction-1", False, overrides
    )


@pytest.mark.parametrize("text", ["play music", "volume up", "hello there"])
def test_non_matching_text_falls_through_without_side_effects(volume, text):
    pipeline = FakePipeline()

    assert call(pipeline, text) is False
    assert pipeline.broadcasts == []
    assert volume["adjustments"] == []


def test_direct_set_executes_and_finishes_the_interaction(volume):
    pipeline = FakePipeline()

    assert call(pipeline, "music volume 75%") is True

    assert volume["sets"] == [75]
    assert pipeline.broadcasts == [("log", "Argo: Music volume set to 75%")]
    assert pipeline.spoken[0][0] == "Music volume set to 75%"
    assert pipeline.transitions == [(('LISTENING',), {'interaction_id': 'interaction-1', 'source': 'audio'})]
    assert pipeline.timeline == [(('INTERACTION_END',), {'stage': 'pipeline', 'interaction_id': 'interaction-1'})]


def test_question_form_does_not_mutate_volume(volume):
    pipeline = FakePipeline()

    assert call(pipeline, "music volume 40?", kind="QUESTION") is True
    assert pipeline.broadcasts[-1][1].endswith("Say it as a command to execute.")
    assert volume["sets"] == []


@pytest.mark.parametrize(
    ("text", "adjustment"),
    [
        ("music volume up", 10),
        ("music volume up 5", 5),
        ("music volume down", -10),
        ("music volume down 7", -7),
    ],
)
def test_explicit_music_volume_adjustments_are_reachable(volume, text, adjustment):
    pipeline = FakePipeline()

    assert call(pipeline, text) is True
    assert volume["adjustments"] == [adjustment]
    assert pipeline.broadcasts[-1][1] == f"Argo: Music volume set to {40 + adjustment}%"


@pytest.mark.parametrize("text", ["what is the music volume", "current music volume"])
def test_explicit_music_volume_status_is_reachable_without_mutation(volume, text):
    pipeline = FakePipeline()

    assert call(pipeline, text, kind="QUESTION") is True
    assert volume["sets"] == []
    assert volume["adjustments"] == []
    assert pipeline.broadcasts[-1] == ("log", "Argo: Music volume: 40%")


def test_unqualified_system_volume_language_still_falls_through(volume):
    pipeline = FakePipeline()

    assert call(pipeline, "volume up 5") is False
    assert call(pipeline, "what is the volume", kind="QUESTION") is False
    assert volume["adjustments"] == []


def test_low_confidence_command_is_not_executed(volume):
    pipeline = FakePipeline()

    assert call(pipeline, "music volume 70", low_confidence=True) is True
    assert volume["sets"] == []
    assert "audio was unclear" in pipeline.broadcasts[-1][1]


def test_policy_block_is_reported_without_mutation(volume):
    pipeline = FakePipeline(gate=(False, "locked"))

    assert call(pipeline, "music volume 70") is True
    assert volume["sets"] == []
    assert pipeline.broadcasts[-1] == ("log", "Argo: Action blocked by policy (locked).")


def test_tts_suppression_preserves_non_voice_completion(volume):
    pipeline = FakePipeline()

    assert call(
        pipeline, "music volume up 5", overrides={"suppress_tts": True}
    ) is True
    assert pipeline.spoken == []
    assert volume["adjustments"] == [5]
