from pathlib import Path
from types import SimpleNamespace

import core.pipeline_draft_responses as responses
from core.pipeline import ArgoPipeline


class _Logger:
    def __init__(self):
        self.errors = []

    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        self.errors.append(args)


class _Pipeline(responses.PipelineDraftResponseMixin):
    def __init__(self):
        self.logger = _Logger()
        self.deliveries = []

    def _deliver_canonical_response(self, message, *args, **kwargs):
        self.deliveries.append((message, args, kwargs))
        return True


def _draft(**overrides):
    values = {
        "category": "email",
        "name": "status update",
        "word_count": 4,
        "content": "To: tommy@example.com\n\nTest message",
        "path": Path("draft.md"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _call(pipeline, method, text):
    return getattr(pipeline, method)(None, text, "interaction-1", False, {})


def test_pipeline_composes_draft_service_and_preserves_public_facade():
    assert not issubclass(ArgoPipeline, responses.PipelineDraftResponseMixin)
    pipeline = object.__new__(ArgoPipeline)
    calls = []
    names = (
        "_respond_with_list_drafts",
        "_respond_with_read_draft",
        "_respond_with_send_email",
        "_respond_with_search_docs",
        "_respond_with_export_data",
    )
    pipeline._draft_responses = type(
        "DraftDouble",
        (),
        {
            name: (lambda method_name: lambda _self, *args, **kwargs: calls.append(
                (method_name, args, kwargs)
            ) or True)(name)
            for name in names
        },
    )()

    for name in names:
        assert getattr(pipeline, name)(None, "text", "id", False, {}) is True

    assert [name for name, _args, _kwargs in calls] == list(names)


def test_list_drafts_preserves_category_filter(monkeypatch):
    pipeline = _Pipeline()
    calls = []
    monkeypatch.setattr(
        responses,
        "list_drafts",
        lambda **kwargs: calls.append(kwargs) or [_draft()],
    )

    assert _call(pipeline, "_respond_with_list_drafts", "list email drafts") is True
    assert calls == [{"category": "email", "limit": 5}]
    assert pipeline.deliveries[0][0] == (
        "You have 1 recent drafts. 1. email: status update, 4 words."
    )


def test_read_draft_truncates_long_content(monkeypatch):
    pipeline = _Pipeline()
    monkeypatch.setattr(
        responses,
        "get_latest_draft",
        lambda **kwargs: _draft(category="note", content=" ".join(["word"] * 151)),
    )

    assert _call(pipeline, "_respond_with_read_draft", "read my note") is True
    message, _, options = pipeline.deliveries[0]
    assert message.endswith("... That's the first 150 words. The full draft is saved.")
    assert options["enforce_confidence"] is False
    assert options["suppress_barge_in_seconds"] == 2.0


def test_send_email_uses_address_from_saved_draft(monkeypatch):
    pipeline = _Pipeline()
    sends = []
    monkeypatch.setattr(responses, "is_email_configured", lambda: True)
    monkeypatch.setattr(responses, "get_latest_draft", lambda **kwargs: _draft())
    monkeypatch.setattr(
        responses,
        "send_draft",
        lambda path, address: sends.append((path, address)) or True,
    )

    assert _call(pipeline, "_respond_with_send_email", "send the email") is True
    assert sends == [("draft.md", "tommy@example.com")]
    assert pipeline.deliveries[0][0] == "Email sent to tommy@example.com successfully."


def test_search_docs_extracts_query(monkeypatch):
    pipeline = _Pipeline()
    calls = []
    monkeypatch.setattr(
        responses,
        "search_drafts",
        lambda query, limit: calls.append((query, limit)) or [_draft(category="note")],
    )

    assert _call(pipeline, "_respond_with_search_docs", "search my notes for coolant") is True
    assert calls == [("coolant", 5)]
    assert pipeline.deliveries[0][0].startswith("Found 1 matches for 'coolant'.")


def test_export_failure_is_contained(monkeypatch):
    pipeline = _Pipeline()
    monkeypatch.setattr(
        responses,
        "parse_spreadsheet_request",
        lambda text: {"data_source": "brain_facts"},
    )
    monkeypatch.setattr(
        responses,
        "export_brain_facts_to_csv",
        lambda: (_ for _ in ()).throw(RuntimeError("disk unavailable")),
    )

    assert _call(pipeline, "_respond_with_export_data", "export brain facts") is True
    assert pipeline.deliveries[0][0] == "Export failed. Check the logs for details."
    assert pipeline.logger.errors
