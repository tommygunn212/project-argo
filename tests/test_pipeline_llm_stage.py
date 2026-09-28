from types import SimpleNamespace

import pytest

from core.pipeline_llm_stage import run_llm_stage


class Brain:
    def __init__(self):
        self.calls = []

    def before_llm(self, *args):
        self.calls.append(("before", args))

    def after_llm(self, *args):
        self.calls.append(("after", args))


class ContextFetcher:
    def __init__(self, missing=()):
        self.missing = list(missing)
        self.calls = []

    def fetch(self, providers, **kwargs):
        self.calls.append((tuple(providers), kwargs))
        return {name: provider() for name, provider in providers.items()}, self.missing


class ConversationBuffer:
    def __init__(self):
        self.calls = []

    def add(self, *args):
        self.calls.append(args)


class FakePipeline:
    def __init__(self, response="answer", missing=()):
        self.response = response
        self.stop_signal = object()
        self._brain = Brain()
        self._context_fetcher = ContextFetcher(missing)
        self._conversation_buffer = ConversationBuffer()
        self.recovery_manager = SimpleNamespace(retry_callback="old")
        self.logs = []
        self.logger = SimpleNamespace(
            info=lambda *args: self.logs.append(("info", args)),
            warning=lambda *args: self.logs.append(("warning", args)),
        )
        self.calls = []

    def _get_rag_context(self, *args):
        self.calls.append(("rag", args))
        return "rag context"

    def _get_memory_context(self, *args, **kwargs):
        self.calls.append(("memory", args, kwargs))
        return "memory context"

    def transition_state(self, *args, **kwargs):
        self.calls.append(("transition", args, kwargs))

    def _generate_and_speak_streamed(self, *args, **kwargs):
        self.calls.append(("generate", args, kwargs))
        return self.response

    def _strip_disallowed_phrases(self, text):
        self.calls.append(("strip", (text,)))
        return text

    def _resolve_personality_mode(self):
        return "default"

    def broadcast(self, *args):
        self.calls.append(("broadcast", args))

    def _recover_failed_turn(self, *args):
        self.calls.append(("recover", args))

    def _append_convo_ledger(self, *args):
        self.calls.append(("ledger", args))

    def _store_durable_turn(self, *args):
        self.calls.append(("durable", args))

    def _record_timeline(self, *args, **kwargs):
        self.calls.append(("timeline", args, kwargs))

    def _save_replay(self, **kwargs):
        self.calls.append(("replay", kwargs))


@pytest.fixture(autouse=True)
def identity_persona(monkeypatch):
    monkeypatch.setattr(
        "core.pipeline_llm_stage.apply_persona",
        lambda text, _response_type, _persona: f"formatted:{text}" if text else text,
    )


def test_question_fetches_context_streams_and_persists_completed_turn():
    pipeline = FakePipeline(response="answer", missing=("slow-provider",))
    intent = SimpleNamespace(intent_type=SimpleNamespace(value="question"))

    run_llm_stage(
        pipeline,
        intent,
        "tell me",
        "QUESTION",
        "interaction-1",
        False,
        {"suppress_tts": True},
        b"audio",
    )

    generate = next(call for call in pipeline.calls if call[0] == "generate")
    assert generate[2]["rag_context"] == "rag context"
    assert generate[2]["memory_context"] == "memory context"
    assert generate[2]["use_convo_buffer"] is True
    assert pipeline._brain.calls == [
        ("before", ("tell me", "question")),
        ("after", ("tell me", "formatted:answer", "question")),
    ]
    assert pipeline._conversation_buffer.calls == [("Assistant", "formatted:answer")]
    assert ("durable", ("tell me", "formatted:answer", "question", "interaction-1")) in pipeline.calls
    replay = next(call for call in pipeline.calls if call[0] == "replay")
    assert replay[1]["audio_data"] == b"audio"
    assert pipeline.recovery_manager.retry_callback is None


def test_non_question_uses_isolated_context_without_fetching():
    pipeline = FakePipeline(response="answer")

    run_llm_stage(
        pipeline, None, "hello", "STATEMENT", "interaction-1", True, None, b"audio"
    )

    assert pipeline._context_fetcher.calls == []
    generate = next(call for call in pipeline.calls if call[0] == "generate")
    assert generate[2]["rag_context"] == ""
    assert generate[2]["memory_context"] == ""
    assert generate[2]["use_convo_buffer"] is False
    assert not any(call[0] == "replay" for call in pipeline.calls)


def test_empty_response_sets_safe_retry_without_persisting_turn():
    pipeline = FakePipeline(response="")

    run_llm_stage(
        pipeline, None, "hello", "QUESTION", "interaction-1", False, None, None
    )

    assert callable(pipeline.recovery_manager.retry_callback)
    assert ("broadcast", ("log", "Argo: [No response]")) in pipeline.calls
    assert ("recover", ("interaction-1",)) in pipeline.calls
    assert pipeline._conversation_buffer.calls == []
    assert not any(call[0] in {"durable", "ledger", "replay"} for call in pipeline.calls)


def test_empty_replay_does_not_install_live_retry_callback():
    pipeline = FakePipeline(response="")

    run_llm_stage(
        pipeline, None, "hello", "QUESTION", "interaction-1", True, None, None
    )

    assert pipeline.recovery_manager.retry_callback == "old"
