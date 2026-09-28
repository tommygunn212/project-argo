from types import SimpleNamespace

import pytest

from core.pipeline_pre_intent_gates import dispatch_pre_intent_gate


class Buffer:
    def __init__(self):
        self.calls = []

    def clear(self, **kwargs):
        self.calls.append(kwargs)


class FakePipeline:
    def __init__(self):
        self.strict_lab_mode = False
        self._conversation_buffer = Buffer()
        self.stop_signal = SimpleNamespace(is_set=lambda: False)
        self.non_propositional = False
        self.memory_handled = False
        self.contextual_reply = None
        self.calls = []
        self.logger = SimpleNamespace(info=lambda *args: self.calls.append(("info", args)))

    def _is_non_propositional_utterance(self, *_args):
        return self.non_propositional

    def _record_timeline(self, *args, **kwargs):
        self.calls.append(("timeline", args, kwargs))

    def _respond_with_clarification(self, *args):
        self.calls.append(("clarify", args))

    def _handle_memory_command(self, *args):
        self.calls.append(("memory", args))
        return self.memory_handled

    def _handle_contextual_followup(self, _text):
        return self.contextual_reply

    def broadcast(self, *args):
        self.calls.append(("broadcast", args))

    def _append_convo_ledger(self, *args):
        self.calls.append(("ledger", args))

    def _sanitize_tts_text(self, text):
        return text

    def speak(self, *args, **kwargs):
        self.calls.append(("speak", args, kwargs))

    def transition_state(self, *args, **kwargs):
        self.calls.append(("transition", args, kwargs))


def test_non_propositional_text_clarifies_before_other_gates():
    pipeline = FakePipeline()
    pipeline.non_propositional = True

    assert dispatch_pre_intent_gate(
        pipeline, "hmm", "QUESTION", None, "interaction-1", False, None
    ) is True
    assert any(call[0] == "clarify" for call in pipeline.calls)
    assert not any(call[0] == "memory" for call in pipeline.calls)


def test_personal_question_requires_canonical_stage_to_release_topic():
    pipeline = FakePipeline()

    with pytest.raises(AssertionError, match="must never be blocked"):
        dispatch_pre_intent_gate(
            pipeline,
            "question",
            "QUESTION",
            "BLOCKED",
            "interaction-1",
            False,
            None,
        )


def test_stop_with_active_music_clears_context_and_stops_player(monkeypatch):
    pipeline = FakePipeline()
    player = SimpleNamespace(
        is_playing=lambda: True,
        stop=lambda: pipeline.calls.append(("music_stop",)),
    )
    monkeypatch.setattr("core.music_player.get_music_player", lambda: player)

    assert dispatch_pre_intent_gate(
        pipeline, "stop music", "ACTION", None, "interaction-1", False, None
    ) is True
    assert pipeline._conversation_buffer.calls == [{"reason": "STOP detected"}]
    assert ("music_stop",) in pipeline.calls


def test_stop_without_active_music_clears_context_then_falls_through(monkeypatch):
    pipeline = FakePipeline()
    player = SimpleNamespace(is_playing=lambda: False)
    monkeypatch.setattr("core.music_player.get_music_player", lambda: player)

    assert dispatch_pre_intent_gate(
        pipeline, "stop talking", "ACTION", None, "interaction-1", False, None
    ) is False
    assert pipeline._conversation_buffer.calls == [{"reason": "STOP detected"}]
    assert any(call[0] == "memory" for call in pipeline.calls)


def test_memory_command_finishes_interaction_before_contextual_followup():
    pipeline = FakePipeline()
    pipeline.memory_handled = True
    pipeline.contextual_reply = "should not run"

    assert dispatch_pre_intent_gate(
        pipeline, "remember this", "ACTION", None, "interaction-1", False, None
    ) is True
    assert any(call[0] == "transition" for call in pipeline.calls)
    assert not any(call[0] == "broadcast" for call in pipeline.calls)


def test_contextual_followup_is_spoken_recorded_and_completed():
    pipeline = FakePipeline()
    pipeline.contextual_reply = "Context answer"

    assert dispatch_pre_intent_gate(
        pipeline, "and then", "QUESTION", None, "interaction-1", False, None
    ) is True
    assert ("broadcast", ("log", "Argo: Context answer")) in pipeline.calls
    assert ("ledger", ("argo", "Context answer")) in pipeline.calls
    assert any(call[0] == "speak" for call in pipeline.calls)


def test_unmatched_text_falls_through():
    pipeline = FakePipeline()

    assert dispatch_pre_intent_gate(
        pipeline, "ordinary", "STATEMENT", None, "interaction-1", False, None
    ) is False
