from types import SimpleNamespace

import core.coordinator_music_stage as stage
from core.intent_parser import IntentType


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))


class _Probe:
    def __init__(self):
        self.marks = []

    def mark(self, name):
        self.marks.append(name)


class _Player:
    def __init__(self):
        self.playing = False
        self.blocked = None
        self.stopped = False
        self.next_result = False
        self.random_result = False
        self.song_result = False
        self.artist_result = False
        self.genre_result = False
        self.keyword_result = False
        self.calls = []

    def is_playing(self):
        return self.playing

    def preflight(self):
        return self.blocked

    def stop(self):
        self.stopped = True

    def play_next(self, sink):
        self.calls.append(("next", sink))
        return self.next_result

    def play_random(self, sink):
        self.calls.append(("random", sink))
        return self.random_result

    def play_by_song(self, value, sink):
        self.calls.append(("song", value, sink))
        return self.song_result

    def play_by_artist(self, value, sink):
        self.calls.append(("artist", value, sink))
        return self.artist_result

    def play_by_genre(self, value, sink):
        self.calls.append(("genre", value, sink))
        return self.genre_result

    def play_by_keyword(self, value, sink):
        self.calls.append(("keyword", value, sink))
        return self.keyword_result


def _coordinator():
    coordinator = SimpleNamespace(
        logger=_Logger(),
        interaction_count=3,
        interaction_id=11,
        runtime_overrides={"music_enabled": True, "tts_enabled": True},
        current_probe=_Probe(),
        sink=object(),
        spoken=[],
        releases=[],
        acquisitions=[],
        monitored=[],
        _last_utterance_time=None,
    )
    coordinator._safe_speak = lambda text, interaction_id=None: coordinator.spoken.append(
        (text, interaction_id)
    )
    coordinator.release_audio = lambda owner: coordinator.releases.append(owner)
    coordinator.acquire_audio = lambda owner: coordinator.acquisitions.append(owner)
    coordinator._monitor_music_interrupt = lambda player: coordinator.monitored.append(player)
    return coordinator


def _intent(intent_type, **values):
    defaults = {
        "keyword": None,
        "artist": None,
        "title": None,
        "explicit_genre": False,
        "is_generic_play": False,
    }
    defaults.update(values)
    return SimpleNamespace(intent_type=intent_type, **defaults)


def _dispatch(coordinator, intent):
    callbacks = []
    result = stage.dispatch_music_stage(
        coordinator,
        intent,
        lambda: callbacks.append("output"),
        lambda: callbacks.append("finalized"),
    )
    return result, callbacks


def test_stop_phrase_only_consumes_turn_when_music_is_active(monkeypatch):
    coordinator = _coordinator()
    player = _Player()
    monkeypatch.setattr(stage, "get_music_player", lambda: player)
    callbacks = []

    assert stage.stop_active_music_for_phrase(
        coordinator, "please stop", lambda: callbacks.append("finalized")
    ) is False
    player.playing = True
    assert stage.stop_active_music_for_phrase(
        coordinator, "please stop", lambda: callbacks.append("finalized")
    ) is True
    assert player.stopped is True
    assert callbacks == ["finalized"]


def test_non_music_intent_falls_through_without_side_effects():
    coordinator = _coordinator()

    result, callbacks = _dispatch(coordinator, _intent(IntentType.QUESTION))

    assert result.routed is False
    assert callbacks == []
    assert coordinator.current_probe.marks == []


def test_music_stop_releases_audio_and_finalizes_after_output(monkeypatch):
    coordinator = _coordinator()
    player = _Player()
    monkeypatch.setattr(stage, "get_music_player", lambda: player)

    result, callbacks = _dispatch(coordinator, _intent(IntentType.MUSIC_STOP))

    assert result.return_interaction is True
    assert result.output_produced is True
    assert player.stopped is True
    assert coordinator.releases == ["MUSIC"]
    assert coordinator.spoken == [("Stopped.", 11)]
    assert callbacks == ["output", "finalized"]
    assert coordinator.current_probe.marks == ["llm_end"]


def test_music_next_without_playback_speaks_and_finishes(monkeypatch):
    coordinator = _coordinator()
    player = _Player()
    monkeypatch.setattr(stage, "get_music_player", lambda: player)

    result, callbacks = _dispatch(coordinator, _intent(IntentType.MUSIC_NEXT))

    assert result.return_interaction is True
    assert coordinator.spoken == [("No music playing.", 11)]
    assert callbacks == ["output", "finalized"]


def test_music_status_uses_read_only_status_query(monkeypatch):
    coordinator = _coordinator()
    monkeypatch.setattr(stage, "query_music_status", lambda: "Playing Test Track")

    result, callbacks = _dispatch(coordinator, _intent(IntentType.MUSIC_STATUS))

    assert result.return_interaction is True
    assert coordinator.spoken == [("Playing Test Track", 11)]
    assert callbacks == ["output", "finalized"]


def test_disabled_music_preserves_legacy_early_return_without_finalize():
    coordinator = _coordinator()
    coordinator.runtime_overrides["music_enabled"] = False

    result, callbacks = _dispatch(coordinator, _intent(IntentType.MUSIC))

    assert result.return_interaction is True
    assert coordinator.spoken == [("Music is disabled.", 11)]
    assert callbacks == []
    assert coordinator.current_probe.marks == ["llm_end"]


def test_unresolved_title_releases_music_audio_and_marks_intent(monkeypatch):
    coordinator = _coordinator()
    player = _Player()
    monkeypatch.setattr(stage, "get_music_player", lambda: player)
    intent = _intent(IntentType.MUSIC, title="Missing Song")

    result, callbacks = _dispatch(coordinator, intent)

    assert result.return_interaction is True
    assert result.is_music_iteration is True
    assert intent.unresolved is True
    assert coordinator.releases == ["MUSIC"]
    assert coordinator.spoken == [("I can’t find that track in your library.", 11)]
    assert callbacks == ["output", "finalized"]


def test_successful_keyword_playback_continues_common_post_processing(monkeypatch):
    coordinator = _coordinator()
    player = _Player()
    player.keyword_result = True
    monkeypatch.setattr(stage, "get_music_player", lambda: player)

    result, callbacks = _dispatch(
        coordinator, _intent(IntentType.MUSIC, keyword="jazz")
    )

    assert result.routed is True
    assert result.return_interaction is False
    assert result.is_music_iteration is True
    assert result.output_produced is True
    assert coordinator.acquisitions == ["MUSIC"]
    assert coordinator.monitored == [player]
    assert callbacks == ["output"]
    assert coordinator.current_probe.marks == ["llm_end"]


def test_title_match_preserves_legacy_random_followup_without_keyword(monkeypatch):
    coordinator = _coordinator()
    player = _Player()
    player.song_result = True
    player.random_result = True
    monkeypatch.setattr(stage, "get_music_player", lambda: player)

    result, _callbacks = _dispatch(
        coordinator, _intent(IntentType.MUSIC, title="Known Song")
    )

    assert result.return_interaction is False
    assert player.calls == [
        ("song", "Known Song", None),
        ("random", None),
    ]
