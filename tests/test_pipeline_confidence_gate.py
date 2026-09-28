from types import SimpleNamespace

import pytest

from core.intent_parser import IntentType
from core.pipeline_confidence_gate import apply_confidence_gate


class FakeParser:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def parse(self, text):
        self.calls.append(text)
        if self.error:
            raise self.error
        return self.result


class FakePipeline:
    def __init__(self, *, strict=False, parsed_intent=None):
        self.strict_lab_mode = strict
        self._personal_mode_min_confidence = 0.5
        self._personal_mode_min_text_len = 3
        self._intent_parser = FakeParser(parsed_intent)
        self._low_conf_notice_given = False
        self.runtime_overrides = {"tts_enabled": True}
        self.calls = []
        self.logger = SimpleNamespace(
            info=lambda *args: self.calls.append(("info", args)),
            warning=lambda *args: self.calls.append(("warning", args)),
        )

    def _allow_low_conf_music_command(self, intent, _text):
        return intent.intent_type == IntentType.MUSIC

    def _is_executable_command(self, _text):
        return True

    def _record_timeline(self, *args, **kwargs):
        self.calls.append(("timeline", args, kwargs))

    def speak(self, *args, **kwargs):
        self.calls.append(("speak", args, kwargs))

    def transition_state(self, *args, **kwargs):
        self.calls.append(("transition", args, kwargs))


def test_high_confidence_personal_text_keeps_original_intent_without_reparse():
    original = SimpleNamespace(intent_type=IntentType.APP_STATUS)
    pipeline = FakePipeline(parsed_intent=SimpleNamespace(intent_type=IntentType.MUSIC))

    result = apply_confidence_gate(
        pipeline, "normal request", 0.9, original, "interaction-1"
    )

    assert result.handled is False
    assert result.intent is original
    assert pipeline._intent_parser.calls == []


def test_low_confidence_personal_text_returns_reparsed_music_intent():
    reparsed = SimpleNamespace(intent_type=IntentType.MUSIC)
    pipeline = FakePipeline(parsed_intent=reparsed)

    result = apply_confidence_gate(
        pipeline, "play music", 0.2, None, "interaction-1"
    )

    assert result.handled is False
    assert result.intent is reparsed
    assert pipeline._intent_parser.calls == ["play music"]
    assert any("executable music command" in call[1][0] for call in pipeline.calls)


def test_personal_guard_records_metadata_but_never_suppresses_conversation():
    pipeline = FakePipeline(parsed_intent=None)

    result = apply_confidence_gate(pipeline, "yo", 0.1, None, "interaction-1")

    assert result.handled is False
    assert any(call[0] == "timeline" for call in pipeline.calls)
    assert not any(call[0] in {"speak", "transition"} for call in pipeline.calls)


@pytest.mark.parametrize("text", ["unclear words", "okay", "..."])
def test_strict_low_confidence_or_filler_finishes_turn(text):
    pipeline = FakePipeline(strict=True)

    result = apply_confidence_gate(pipeline, text, 0.2, None, "interaction-1")

    assert result.handled is True
    assert pipeline._low_conf_notice_given is True
    assert any(call[0] == "speak" for call in pipeline.calls)
    assert any(call[0] == "transition" for call in pipeline.calls)


def test_strict_notice_is_spoken_only_once():
    pipeline = FakePipeline(strict=True)
    pipeline._low_conf_notice_given = True

    result = apply_confidence_gate(
        pipeline, "unclear words", 0.2, None, "interaction-1"
    )

    assert result.handled is True
    assert not any(call[0] == "speak" for call in pipeline.calls)


@pytest.mark.parametrize("text", ["system status", "count to five", "volume 50", "remember this", "stop music"])
def test_strict_mid_confidence_exceptions_continue(text):
    pipeline = FakePipeline(strict=True)

    result = apply_confidence_gate(pipeline, text, 0.32, None, "interaction-1")

    assert result.handled is False
    assert not any(call[0] in {"speak", "transition"} for call in pipeline.calls)
