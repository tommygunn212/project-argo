import logging
import threading
from types import SimpleNamespace

import pytest

from core.coordinator_response_stage import deliver_and_record_response
from core.intent_models import IntentType


class _Memory:
    def __init__(self):
        self.turns = []

    def append(self, **turn):
        self.turns.append(turn)


class _Probe:
    def __init__(self):
        self.marks = []
        self.summaries = 0

    def mark(self, name):
        self.marks.append(name)

    def log_summary(self):
        self.summaries += 1


def _coordinator(*, streamed=False, tts_enabled=True, speak_error=None):
    probe = _Probe()
    memory = _Memory()
    spoken = []
    host = SimpleNamespace(
        STOP_KEYWORDS=("goodbye", "quit"),
        _is_speaking=threading.Event(),
        builder=SimpleNamespace(write_script=lambda *_: None, open_in_vscode=lambda *_: None),
        current_probe=probe,
        generator=SimpleNamespace(_streamed_output=streamed),
        interaction_count=3,
        latency_stats=SimpleNamespace(probes=[]),
        logger=logging.getLogger("test.coordinator_response_stage"),
        memory=memory,
        runtime_overrides={"tts_enabled": tts_enabled},
        stop_requested=False,
        _last_response=None,
        last_response_text=None,
    )
    host.latency_stats.add_probe = host.latency_stats.probes.append
    host._extract_code_block = lambda _text: None
    host._infer_sandbox_filename = lambda *_: "unused.py"
    host._strip_code_blocks = lambda value: value

    def speak(text):
        spoken.append(text)
        if speak_error:
            raise speak_error

    host._speak_with_interrupt_detection = speak
    return host, probe, memory, spoken


def _deliver(host, text="Answer", *, overrides=None, initial=False):
    return deliver_and_record_response(
        host,
        intent=SimpleNamespace(intent_type=IntentType.QUESTION),
        user_text="Question",
        response_text=text,
        overrides=overrides or {},
        output_produced=initial,
    )


def test_normal_response_speaks_records_and_accounts_for_latency():
    host, probe, memory, spoken = _coordinator()

    assert _deliver(host) is True

    assert spoken == ["Answer"]
    assert host._is_speaking.is_set() is False
    assert probe.marks == ["tts_start", "tts_end"]
    assert probe.summaries == 1
    assert host.latency_stats.probes == [probe]
    assert memory.turns == [{
        "user_utterance": "Question",
        "parsed_intent": "question",
        "generated_response": "Answer",
    }]


def test_streamed_response_is_not_spoken_twice():
    host, _probe, memory, spoken = _coordinator(streamed=True)

    assert _deliver(host) is True

    assert spoken == []
    assert memory.turns[0]["generated_response"] == "Answer"


def test_suppressed_tts_preserves_existing_output_state_and_records_turn():
    host, _probe, memory, spoken = _coordinator()

    assert _deliver(host, overrides={"suppress_tts": True}, initial=True) is True

    assert spoken == []
    assert len(memory.turns) == 1


def test_speaking_flag_is_cleared_when_output_raises():
    host, _probe, memory, _spoken = _coordinator(speak_error=RuntimeError("speaker failed"))

    with pytest.raises(RuntimeError, match="speaker failed"):
        _deliver(host)

    assert host._is_speaking.is_set() is False
    assert memory.turns == []


def test_stop_keyword_sets_stop_request_after_recording():
    host, _probe, memory, _spoken = _coordinator(tts_enabled=False)

    assert _deliver(host, text="Goodbye for now") is False

    assert host.stop_requested is True
    assert len(memory.turns) == 1
