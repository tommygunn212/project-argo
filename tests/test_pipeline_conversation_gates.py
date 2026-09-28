from types import SimpleNamespace

import pytest

from core.pipeline_conversation_gates import dispatch_conversation_gate


class MemoryStore:
    def __init__(self):
        self.calls = []

    def add_memory(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class FakePipeline:
    def __init__(self):
        self.strict_lab_mode = False
        self._session_flags = {}
        self._pending_memory = None
        self._memory_store = MemoryStore()
        self._conversation_ledger = ["old"]
        self.stop_signal = SimpleNamespace(is_set=lambda: False)
        self.calls = []
        self.logger = SimpleNamespace(
            info=lambda *args: self.calls.append(("info", args)),
            warning=lambda *args: self.calls.append(("warning", args)),
        )

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

    def _record_timeline(self, *args, **kwargs):
        self.calls.append(("timeline", args, kwargs))

    def _is_affirmative_response(self, text):
        return text.lower() in {"yes", "yep"}

    def _store_mem0_fact(self, *args):
        self.calls.append(("mem0", args))

    def _is_identity_query(self, text):
        return text == "who am i"

    def _respond_with_identity_lookup(self, **kwargs):
        self.calls.append(("identity", kwargs))
        return True


def response_for(pipeline):
    return next(call[1][1] for call in pipeline.calls if call[0] == "broadcast")


def test_empty_input_finishes_without_recording_ledger():
    pipeline = FakePipeline()

    assert dispatch_conversation_gate(
        pipeline, "", "interaction-1", False, None
    ) is True
    assert response_for(pipeline) == "Argo: I didn't catch any words. Try again."
    assert not any(call[0] == "ledger" for call in pipeline.calls)


@pytest.mark.parametrize("text", ["okay", "Okay.", "...", "okay okay"])
def test_personal_mode_filler_is_acknowledged_and_recorded(text):
    pipeline = FakePipeline()

    assert dispatch_conversation_gate(
        pipeline, text, "interaction-1", False, None
    ) is True
    assert response_for(pipeline) == "Argo: Okay."
    assert ("ledger", ("argo", "Okay.")) in pipeline.calls


def test_filler_falls_through_in_strict_lab_mode():
    pipeline = FakePipeline()
    pipeline.strict_lab_mode = True

    assert dispatch_conversation_gate(
        pipeline, "okay", "interaction-1", False, None
    ) is False
    assert pipeline.calls == []


def test_clear_conversation_empties_ledger_and_finishes():
    pipeline = FakePipeline()

    assert dispatch_conversation_gate(
        pipeline, "clear conversation", "interaction-1", False, None
    ) is True
    assert pipeline._conversation_ledger == []
    assert response_for(pipeline) == "Argo: Conversation cleared."


def test_identity_query_delegates_to_existing_lookup_handler():
    pipeline = FakePipeline()

    assert dispatch_conversation_gate(
        pipeline, "who am i", "interaction-1", False, None
    ) is True
    assert any(call[0] == "identity" for call in pipeline.calls)


def test_affirmative_name_confirmation_writes_only_explicit_memory():
    pipeline = FakePipeline()
    pipeline._session_flags["confirm_name"] = True
    pipeline._pending_memory = {"key": "name", "value": "Tommy"}

    assert dispatch_conversation_gate(
        pipeline, "yes", "interaction-1", False, None
    ) is True
    assert pipeline._memory_store.calls == [
        (("FACT", "name", "Tommy"), {"source": "explicit_user_request"})
    ]
    assert pipeline._pending_memory is None
    assert pipeline._session_flags["confirm_name"] is False
    assert response_for(pipeline) == "Argo: Got it. I'll remember that."


def test_negative_name_confirmation_clears_pending_memory_without_write():
    pipeline = FakePipeline()
    pipeline._session_flags["confirm_name"] = True
    pipeline._pending_memory = {"key": "name", "value": "Wrong"}

    assert dispatch_conversation_gate(
        pipeline, "no", "interaction-1", False, None
    ) is True
    assert pipeline._memory_store.calls == []
    assert pipeline._pending_memory is None
    assert response_for(pipeline) == "Argo: Okay."


def test_unrelated_text_falls_through_without_side_effects():
    pipeline = FakePipeline()

    assert dispatch_conversation_gate(
        pipeline, "tell me a story", "interaction-1", False, None
    ) is False
    assert pipeline.calls == []
