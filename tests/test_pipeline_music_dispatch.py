from types import SimpleNamespace

import pytest

from core.intent_parser import IntentType
from core.pipeline_music_dispatch import dispatch_music_intent


class FakePlayer:
    def __init__(self, *, preflight=None, playback=False):
        self.preflight_result = preflight
        self.playback = playback
        self.calls = []

    def preflight(self):
        self.calls.append(("preflight",))
        return self.preflight_result

    def stop(self):
        self.calls.append(("stop",))

    def play_next(self, value):
        self.calls.append(("play_next", value))
        return self.playback

    def play_random(self, value):
        self.calls.append(("play_random", value))
        return self.playback

    def play_by_song(self, value, context):
        self.calls.append(("play_by_song", value, context))
        return self.playback

    def play_by_artist(self, value, context):
        self.calls.append(("play_by_artist", value, context))
        return self.playback

    def play_by_genre(self, value, context):
        self.calls.append(("play_by_genre", value, context))
        return self.playback

    def play_by_keyword(self, value, context):
        self.calls.append(("play_by_keyword", value, context))
        return self.playback


class FakePipeline:
    def __init__(self, *, music_enabled=True, gate=(True, "allowed")):
        self.runtime_overrides = {"tts_enabled": True, "music_enabled": music_enabled}
        self.gate = gate
        self.stop_signal = SimpleNamespace(is_set=lambda: False)
        self.logs = []
        self.logger = SimpleNamespace(info=lambda *args, **kwargs: self.logs.append(args))
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

    def _allow_low_conf_music_command(self, _intent, _text):
        return False

    def _is_executable_command(self, _text):
        return True

    def _evaluate_gates(self, *args):
        self.gate_args = args
        return self.gate


def intent(intent_type, **fields):
    return SimpleNamespace(intent_type=intent_type, **fields)


def call(pipeline, parsed_intent, *, text="play music", kind="ACTION", low=False):
    return dispatch_music_intent(
        pipeline,
        parsed_intent,
        text,
        kind,
        low,
        0.9,
        "interaction-1",
        False,
        None,
    )


@pytest.mark.parametrize("parsed_intent", [None, intent(IntentType.APP_STATUS)])
def test_non_music_intents_fall_through_without_side_effects(parsed_intent):
    pipeline = FakePipeline()

    assert call(pipeline, parsed_intent) is False
    assert pipeline.spoken == []
    assert pipeline.transitions == []


def test_non_action_music_request_is_guarded_before_player_access(monkeypatch):
    pipeline = FakePipeline()
    monkeypatch.setattr(
        "core.pipeline_music_dispatch.get_music_player",
        lambda: pytest.fail("player should not be accessed"),
    )

    assert call(pipeline, intent(IntentType.MUSIC), kind="QUESTION") is True
    assert pipeline.broadcasts[-1][1].endswith("Say it as a command to execute.")
    assert pipeline.transitions[-1][0] == ("LISTENING",)
    assert pipeline.timeline[-1][0] == ("INTERACTION_END",)


def test_disabled_music_stops_after_policy_gate(monkeypatch):
    pipeline = FakePipeline(music_enabled=False)
    monkeypatch.setattr(
        "core.pipeline_music_dispatch.get_music_player",
        lambda: pytest.fail("player should not be accessed"),
    )

    assert call(pipeline, intent(IntentType.MUSIC_STOP), text="stop music") is True
    assert pipeline.gate_args == ("music_playback", "music_player", "interaction-1")
    assert pipeline.spoken[-1][0] == "Music is disabled."


def test_stop_intent_uses_player_and_returns_to_listening(monkeypatch):
    pipeline = FakePipeline()
    player = FakePlayer()
    monkeypatch.setattr("core.pipeline_music_dispatch.get_music_player", lambda: player)

    assert call(pipeline, intent(IntentType.MUSIC_STOP), text="stop music") is True
    assert player.calls == [("preflight",), ("stop",)]
    assert pipeline.spoken[-1][0] == "Stopped."
    assert pipeline.transitions[-1][0] == ("LISTENING",)


def test_status_intent_speaks_status_without_playback(monkeypatch):
    pipeline = FakePipeline()
    player = FakePlayer()
    monkeypatch.setattr("core.pipeline_music_dispatch.get_music_player", lambda: player)
    monkeypatch.setattr(
        "core.pipeline_music_dispatch.query_music_status", lambda: "Nothing playing."
    )

    assert call(pipeline, intent(IntentType.MUSIC_STATUS), text="music status") is True
    assert player.calls == [("preflight",)]
    assert pipeline.spoken[-1][0] == "Nothing playing."


def test_unresolved_title_is_marked_and_reported(monkeypatch):
    pipeline = FakePipeline()
    player = FakePlayer(playback=False)
    parsed_intent = intent(
        IntentType.MUSIC,
        artist=None,
        title="Missing Song",
        keyword=None,
        explicit_genre=False,
        is_generic_play=False,
    )
    monkeypatch.setattr("core.pipeline_music_dispatch.get_music_player", lambda: player)

    assert call(pipeline, parsed_intent, text="play Missing Song") is True
    assert parsed_intent.unresolved is True
    assert ("play_by_song", "Missing Song", None) in player.calls
    assert pipeline.spoken[-1][0] == "I can’t find that track in your library."
