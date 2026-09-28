"""Contract tests for dashboard runtime-override dispatch."""

from types import SimpleNamespace
from unittest.mock import Mock

import main


def _configure(monkeypatch, *, pipeline=True):
    pipeline_ref = SimpleNamespace(
        set_tts_model=Mock(),
        apply_runtime_tuning=Mock(),
    ) if pipeline else None
    set_override = Mock()
    get_overrides = Mock(return_value={"temperature": 0.7})
    event = Mock()
    broadcast = Mock()
    monkeypatch.setattr(main, "pipeline_ref", pipeline_ref)
    monkeypatch.setattr(main, "set_runtime_override", set_override)
    monkeypatch.setattr(main, "get_runtime_overrides", get_overrides)
    monkeypatch.setattr(main, "log_event", event)
    monkeypatch.setattr(main, "broadcast_msg", broadcast)
    return pipeline_ref, set_override, get_overrides, event, broadcast


def test_override_without_key_is_ignored(monkeypatch):
    _, set_override, _, event, broadcast = _configure(monkeypatch)

    main._handle_override({"value": 3})

    set_override.assert_not_called()
    event.assert_not_called()
    broadcast.assert_not_called()


def test_generic_override_updates_pipeline_and_broadcasts_snapshot(monkeypatch):
    pipeline, set_override, get_overrides, event, broadcast = _configure(monkeypatch)

    main._handle_override({"key": "temperature", "value": 0.7})

    set_override.assert_called_once_with("temperature", 0.7)
    pipeline.apply_runtime_tuning.assert_called_once_with()
    event.assert_called_once_with(
        "UI_CMD_SET_OVERRIDE temperature=0.7", stage="ui"
    )
    broadcast.assert_called_once_with("runtime_overrides", get_overrides.return_value)


def test_tts_model_override_updates_classic_pipeline_model(monkeypatch):
    pipeline, *_ = _configure(monkeypatch)

    main._handle_override({"key": "tts_model", "value": "tts-1-hd"})

    pipeline.set_tts_model.assert_called_once_with("tts-1-hd")


def test_personality_override_persists_for_realtime_worker(monkeypatch):
    _, _, _, event, _ = _configure(monkeypatch)
    write = Mock()
    monkeypatch.setattr("core.livekit_config.write_voice_personality", write)

    main._handle_override({"key": "personality_mode", "value": "plain"})

    write.assert_called_once_with("plain")
    assert any(
        call.args[0] == "VOICE_PERSONALITY_PERSISTED plain"
        for call in event.call_args_list
    )


def test_realtime_voice_persistence_failure_is_reported_but_override_survives(
    monkeypatch,
):
    pipeline, set_override, _, event, broadcast = _configure(monkeypatch)
    monkeypatch.setattr(
        "core.livekit_config.write_realtime_voice",
        Mock(side_effect=RuntimeError("disk unavailable")),
    )

    main._handle_override({"key": "realtime_voice", "value": "marin"})

    set_override.assert_called_once_with("realtime_voice", "marin")
    pipeline.apply_runtime_tuning.assert_called_once_with()
    assert any(
        call.args == ("log", "Voice not saved: disk unavailable")
        for call in broadcast.call_args_list
    )
    assert any(
        call.args[0] == "UI_CMD_SET_OVERRIDE realtime_voice=marin"
        for call in event.call_args_list
    )
