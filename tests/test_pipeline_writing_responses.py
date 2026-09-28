from types import SimpleNamespace

import core.pipeline_writing_responses as responses
from core.pipeline import ArgoPipeline


class _Logger:
    def __init__(self):
        self.errors = []

    def info(self, *args, **kwargs):
        pass

    def error(self, message):
        self.errors.append(message)


class _Pipeline(responses.PipelineWritingResponseMixin):
    def __init__(self):
        self.logger = _Logger()
        self.generated = "generated body"
        self.deliveries = []
        self.transitions = []
        self.desktop_payloads = []

    def generate_response(self, prompt, **kwargs):
        return self.generated

    def transition_state(self, state, **kwargs):
        self.transitions.append((state, kwargs))

    def _desktop_write_status(self, content, user_text, interaction_id):
        self.desktop_payloads.append((content, user_text, interaction_id))
        return "Typed into Notepad."

    def _deliver_canonical_response(self, message, *args, **kwargs):
        self.deliveries.append((message, args, kwargs))
        return True


def _call(pipeline, method, text):
    return getattr(pipeline, method)(None, text, "interaction-1", False, {})


def _draft(**values):
    defaults = {"content": "saved content", "word_count": 12}
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_write_email_generates_saves_and_types_draft(monkeypatch):
    pipeline = _Pipeline()
    saved = []
    monkeypatch.setattr(
        responses,
        "parse_email_request",
        lambda text: {"to": "Sarah", "subject": "Status"},
    )
    monkeypatch.setattr(responses, "build_email_prompt", lambda **kwargs: "email prompt")
    monkeypatch.setattr(
        responses,
        "draft_email",
        lambda **kwargs: saved.append(kwargs) or _draft(),
    )

    assert _call(pipeline, "_respond_with_write_email", "email Sarah") is True
    assert saved == [{"to": "Sarah", "subject": "Status", "body": "generated body"}]
    assert pipeline.desktop_payloads[0][0] == "saved content"
    assert pipeline.deliveries[0][0].startswith("Email to Sarah drafted.")


def test_write_email_handles_empty_generation(monkeypatch):
    pipeline = _Pipeline()
    pipeline.generated = ""
    monkeypatch.setattr(
        responses,
        "parse_email_request",
        lambda text: {"to": "", "subject": "Status"},
    )
    monkeypatch.setattr(responses, "build_email_prompt", lambda **kwargs: "email prompt")

    assert _call(pipeline, "_respond_with_write_email", "write email") is True
    assert pipeline.deliveries[0][0] == "I couldn't generate the email. Try again?"


def test_write_note_strips_trigger_and_preserves_content(monkeypatch):
    pipeline = _Pipeline()
    saved = []
    monkeypatch.setattr(
        responses,
        "save_note",
        lambda content: saved.append(content) or _draft(content=content, word_count=3),
    )

    assert _call(pipeline, "_respond_with_write_note", "take a note: buy more filament") is True
    assert saved == ["buy more filament"]
    assert pipeline.deliveries[0][0].startswith("Note saved. 3 words.")


def test_edit_draft_reports_when_no_draft_exists(monkeypatch):
    pipeline = _Pipeline()
    monkeypatch.setattr(
        responses,
        "parse_edit_instruction",
        lambda text: {"category": "email", "instruction": "shorter"},
    )
    monkeypatch.setattr(responses, "get_latest_draft", lambda category=None: None)

    assert _call(pipeline, "_respond_with_edit_draft", "make email shorter") is True
    assert pipeline.deliveries[0][0] == "No drafts found to edit. Write something first!"


def test_writing_llm_failure_is_contained():
    pipeline = _Pipeline()
    pipeline.generate_response = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("provider offline")
    )

    assert pipeline._writing_llm_call("prompt", "interaction-1") == ""
    assert any("provider offline" in message for message in pipeline.logger.errors)


def test_pipeline_composes_writing_service_and_preserves_public_facade():
    assert not issubclass(ArgoPipeline, responses.PipelineWritingResponseMixin)
    pipeline = object.__new__(ArgoPipeline)
    calls = []
    names = (
        "_writing_llm_call",
        "_respond_with_write_email",
        "_respond_with_write_document",
        "_respond_with_write_blog",
        "_respond_with_write_note",
        "_respond_with_edit_draft",
    )
    pipeline._writing_responses = type(
        "WritingDouble",
        (),
        {
            name: (lambda method_name: lambda _self, *args, **kwargs: calls.append(
                (method_name, args, kwargs)
            ) or "ok")(name)
            for name in names
        },
    )()

    assert pipeline._writing_llm_call("prompt", "id") == "ok"
    for name in names[1:]:
        assert getattr(pipeline, name)(None, "text", "id", False, {}) == "ok"
    assert [name for name, _args, _kwargs in calls] == list(names)
