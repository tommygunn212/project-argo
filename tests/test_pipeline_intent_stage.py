from types import SimpleNamespace

import pytest

from core.intent_parser import IntentType
from core.pipeline_intent_stage import prepare_intent_stage


class Buffer:
    def __init__(self):
        self.calls = []

    def clear(self, **kwargs):
        self.calls.append(kwargs)


class FakePipeline:
    def __init__(self, *, strict=False, request_kind="QUESTION"):
        self.strict_lab_mode = strict
        self.classified_kind = request_kind
        self._conversation_buffer = Buffer()
        self._session_flags = {}
        self._pending_memory = None
        self.stop_signal = SimpleNamespace(is_set=lambda: False)
        self.name_candidate = None
        self.ambiguity_prompt = None
        self.calls = []
        self.logger = SimpleNamespace(
            info=lambda *args: self.calls.append(("info", args)),
            warning=lambda *args: self.calls.append(("warning", args)),
        )

    def _classify_request_type(self, _text, _intent):
        return self.classified_kind

    def _music_noun_detected(self, text):
        return "music" in text.lower() or "song" in text.lower()

    def _extract_name_from_statement(self, _text):
        return self.name_candidate

    def _record_timeline(self, *args, **kwargs):
        self.calls.append(("timeline", args, kwargs))

    def _ambiguous_short_question_prompt(self, *_args):
        return self.ambiguity_prompt

    def _respond_with_clarification(self, *args, **kwargs):
        self.calls.append(("clarify", args, kwargs))

    def _get_clarification_prompt(self):
        return "Please clarify."

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


def test_existing_intent_and_question_flow_through_with_safe_log_text():
    pipeline = FakePipeline()
    parsed_intent = SimpleNamespace(
        intent_type=IntentType.APP_STATUS, artist=None, title=None
    )

    result = prepare_intent_stage(
        pipeline,
        parsed_intent,
        "status\nplease",
        None,
        set(),
        0.9,
        "interaction-1",
        False,
        None,
    )

    assert result.handled is False
    assert result.intent is parsed_intent
    assert result.request_kind == "QUESTION"
    assert result.safe_utterance == "status please"
    assert result.low_confidence_audio is False


def test_play_music_fallback_creates_music_intent_and_clears_command_context():
    pipeline = FakePipeline(request_kind="QUESTION")

    result = prepare_intent_stage(
        pipeline,
        None,
        "play jazz music",
        None,
        set(),
        0.9,
        "interaction-1",
        False,
        None,
    )

    assert result.intent.intent_type == IntentType.MUSIC
    assert result.intent.keyword == "jazz music"
    assert result.request_kind == "ACTION"
    assert pipeline._conversation_buffer.calls == [{"reason": "command intent"}]


def test_name_statement_requests_confirmation_and_sets_pending_memory():
    pipeline = FakePipeline()
    pipeline.name_candidate = "Tommy"

    result = prepare_intent_stage(
        pipeline,
        None,
        "my name is Tommy",
        None,
        set(),
        0.9,
        "interaction-1",
        False,
        None,
    )

    assert result.handled is True
    assert pipeline._pending_memory == {"key": "name", "value": "Tommy"}
    assert pipeline._session_flags["confirm_name"] is True
    assert ("ledger", ("argo", "Do you want me to remember that your name is Tommy?")) in pipeline.calls


def test_ambiguous_prompt_delegates_to_existing_clarification_handler():
    pipeline = FakePipeline()
    pipeline.ambiguity_prompt = "Which one?"

    result = prepare_intent_stage(
        pipeline,
        None,
        "which",
        None,
        set(),
        0.9,
        "interaction-1",
        False,
        None,
    )

    assert result.handled is True
    assert any(call[0] == "clarify" for call in pipeline.calls)


def test_personal_low_confidence_question_is_not_blocked():
    pipeline = FakePipeline()

    result = prepare_intent_stage(
        pipeline,
        None,
        "why",
        None,
        set(),
        0.2,
        "interaction-1",
        False,
        None,
    )

    assert result.handled is False
    assert result.low_confidence_audio is True
    assert any("bypassed confidence" in call[1][0] for call in pipeline.calls if call[0] == "info")


def test_strict_mid_confidence_question_requests_clarification_once():
    pipeline = FakePipeline(strict=True)

    result = prepare_intent_stage(
        pipeline,
        None,
        "bananas?",
        None,
        {"bananas"},
        0.4,
        "interaction-1",
        False,
        None,
    )

    assert result.handled is True
    assert pipeline._session_flags["clarification_asked"] is True
    assert ("broadcast", ("log", "Argo: Please clarify.")) in pipeline.calls


def test_strict_phrase_match_skips_confidence_clarification():
    pipeline = FakePipeline(strict=True)

    result = prepare_intent_stage(
        pipeline,
        None,
        "known phrase",
        None,
        {"known phrase"},
        0.4,
        "interaction-1",
        False,
        None,
    )

    assert result.handled is False
    assert "clarification_asked" not in pipeline._session_flags
