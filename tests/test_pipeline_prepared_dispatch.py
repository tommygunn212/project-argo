from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from core import pipeline_prepared_dispatch as dispatch


@pytest.fixture
def prepared_request():
    return dispatch.PreparedDispatch(
        intent=object(),
        user_text="hello",
        request_kind="conversation",
        safe_utterance=True,
        low_confidence_audio=False,
        stt_confidence=0.9,
        interaction_id="turn-1",
        replay_mode=False,
        overrides={"voice": "test"},
        audio_data="audio",
    )


def install_stages(monkeypatch, handled_stage=None):
    calls = []
    names = [
        "dispatch_music_volume",
        "dispatch_music_intent",
        "dispatch_platform_intent",
        "dispatch_special_intent",
        "dispatch_domain_intent",
        "dispatch_system_info",
        "block_restricted_llm_fallback",
        "run_llm_stage",
    ]
    for name in names:
        def stage(*args, _name=name, **kwargs):
            calls.append((_name, args, kwargs))
            return _name == handled_stage
        monkeypatch.setattr(dispatch, name, stage)
    return calls


def test_stages_run_in_explicit_precedence_order(monkeypatch, prepared_request):
    calls = install_stages(monkeypatch)

    dispatch.dispatch_prepared_intent(Mock(), prepared_request)

    assert [name for name, _, _ in calls] == [
        "dispatch_music_volume",
        "dispatch_music_intent",
        "dispatch_platform_intent",
        "dispatch_special_intent",
        "dispatch_domain_intent",
        "dispatch_system_info",
        "block_restricted_llm_fallback",
        "run_llm_stage",
    ]


@pytest.mark.parametrize(
    "handled_stage",
    [
        "dispatch_music_volume",
        "dispatch_music_intent",
        "dispatch_platform_intent",
        "dispatch_special_intent",
        "dispatch_domain_intent",
        "dispatch_system_info",
        "block_restricted_llm_fallback",
    ],
)
def test_first_handled_stage_stops_all_later_dispatch(monkeypatch, prepared_request, handled_stage):
    calls = install_stages(monkeypatch, handled_stage)

    dispatch.dispatch_prepared_intent(Mock(), prepared_request)

    names = [name for name, _, _ in calls]
    assert names[-1] == handled_stage
    assert "run_llm_stage" not in names


def test_llm_fallback_receives_audio_and_context(monkeypatch, prepared_request):
    calls = install_stages(monkeypatch)
    host = Mock()

    dispatch.dispatch_prepared_intent(host, prepared_request)

    _, arguments, _ = calls[-1]
    assert arguments == (
        host,
        prepared_request.intent,
        "hello",
        "conversation",
        "turn-1",
        False,
        {"voice": "test"},
        "audio",
    )


def test_pipeline_facade_builds_prepared_context(monkeypatch):
    from core import pipeline as pipeline_module
    from core.pipeline import ArgoPipeline

    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.logger = Mock()
    pipeline.strict_lab_mode = False
    pipeline._intent_parser = SimpleNamespace(parse=lambda text: None)
    pipeline._classify_request_kind = lambda text: "conversation"
    monkeypatch.setattr(pipeline_module, "dispatch_early_status", lambda *args: False)
    monkeypatch.setattr(pipeline_module, "dispatch_conversation_gate", lambda *args: False)
    monkeypatch.setattr(
        pipeline_module,
        "apply_confidence_gate",
        lambda *args: SimpleNamespace(intent=None, handled=False),
    )
    monkeypatch.setattr(
        pipeline_module,
        "run_canonical_stage",
        lambda *args: SimpleNamespace(handled=False, topic="general", matched=False),
    )
    monkeypatch.setattr(pipeline_module, "dispatch_pre_intent_gate", lambda *args: False)
    intent = object()
    monkeypatch.setattr(
        pipeline_module,
        "prepare_intent_stage",
        lambda *args: SimpleNamespace(
            handled=False,
            intent=intent,
            request_kind="knowledge",
            safe_utterance=True,
            low_confidence_audio=False,
        ),
    )
    captured = []
    monkeypatch.setattr(
        pipeline_module,
        "dispatch_prepared_intent",
        lambda host, context: captured.append((host, context)),
    )

    pipeline.handle_user_text(
        "  hello  ",
        confidence_hint=2.0,
        interaction_id="turn-2",
        overrides={"mode": "test"},
        audio_data="samples",
    )

    host, context = captured[0]
    assert host is pipeline
    assert context.user_text == "hello"
    assert context.intent is intent
    assert context.stt_confidence == 1.0
    assert context.interaction_id == "turn-2"
    assert context.audio_data == "samples"
