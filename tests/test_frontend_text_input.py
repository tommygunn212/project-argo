"""Characterization tests for frontend text-input dispatch."""

from types import SimpleNamespace
from unittest.mock import Mock

import main


class _ImmediateThread:
    def __init__(self, *, target, **_kwargs):
        self.target = target

    def start(self):
        self.target()


def _pipeline(state="LISTENING"):
    return SimpleNamespace(
        current_state=state,
        transition_state=Mock(),
        _normalize_music_command_text=Mock(side_effect=lambda text: text),
        broadcast=Mock(),
        _conversation_buffer=SimpleNamespace(add=Mock()),
        _broadcast_turn_info=Mock(),
        _append_convo_ledger=Mock(),
        handle_user_text=Mock(),
    )


def _install(monkeypatch, pipeline):
    monkeypatch.setattr(main, "pipeline_ref", pipeline)
    monkeypatch.setattr(main, "log_event", Mock())
    monkeypatch.setattr(main.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(main, "_interrupt_current_response", Mock())
    main.NEXT_INTERACTION_OVERRIDES.clear()


def test_empty_text_input_is_ignored(monkeypatch):
    pipeline = _pipeline()
    _install(monkeypatch, pipeline)

    main._handle_text_input({"text": "   "})

    pipeline.transition_state.assert_not_called()
    pipeline.handle_user_text.assert_not_called()
    main.log_event.assert_not_called()


def test_text_input_interrupts_speech_and_routes_normalized_text(monkeypatch):
    pipeline = _pipeline(state="SPEAKING")
    _install(monkeypatch, pipeline)
    main.NEXT_INTERACTION_OVERRIDES["suppress_tts"] = True
    monkeypatch.setattr(
        "core.intent_parser.normalize_system_text",
        Mock(return_value="normalized text"),
    )
    pipeline._normalize_music_command_text.side_effect = lambda _text: "music normalized"

    main._handle_text_input(
        {"text": " raw text ", "source": "dashboard", "mode": "command"}
    )

    main._interrupt_current_response.assert_called_once_with(
        "TEXT_BARGE_IN", target_state="LISTENING"
    )
    pipeline.transition_state.assert_called_once()
    transition = pipeline.transition_state.call_args
    assert transition.args == ("THINKING",)
    assert transition.kwargs["source"] == "text_input"
    interaction_id = transition.kwargs["interaction_id"]
    pipeline._conversation_buffer.add.assert_called_once_with(
        "User", "music normalized"
    )
    pipeline.handle_user_text.assert_called_once_with(
        user_text="music normalized",
        confidence_hint=1.0,
        interaction_id=interaction_id,
        replay_mode=False,
        overrides={"suppress_tts": True},
        audio_data=None,
    )
    assert main.NEXT_INTERACTION_OVERRIDES == {}


def test_text_input_pipeline_failure_broadcasts_error_and_clears_override(
    monkeypatch,
):
    pipeline = _pipeline()
    pipeline.handle_user_text.side_effect = RuntimeError("routing failed")
    _install(monkeypatch, pipeline)
    main.NEXT_INTERACTION_OVERRIDES["suppress_tts"] = True

    main._handle_text_input("hello")

    pipeline.broadcast.assert_any_call("status", "ERROR")
    assert main.NEXT_INTERACTION_OVERRIDES == {}
