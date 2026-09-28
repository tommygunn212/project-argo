from datetime import datetime, timedelta

import core.pipeline_scheduling_responses as responses


class _Logger:
    def info(self, *args, **kwargs):
        pass


class _Pipeline(responses.PipelineSchedulingResponseMixin):
    def __init__(self):
        self.logger = _Logger()
        self.deliveries = []

    def _deliver_canonical_response(self, message, *args, **kwargs):
        self.deliveries.append((message, args, kwargs))
        return True


def _call(pipeline, method, text):
    return getattr(pipeline, method)(None, text, "interaction-1", False, {})


def test_set_reminder_preserves_parsing_and_storage(monkeypatch):
    pipeline = _Pipeline()
    due_at = datetime.now() + timedelta(minutes=30)
    added = []
    monkeypatch.setattr(
        responses,
        "parse_reminder_request",
        lambda text: {"message": "call Sarah", "due_at": due_at},
    )
    monkeypatch.setattr(
        responses,
        "add_reminder",
        lambda message, due: added.append((message, due)),
    )

    assert _call(pipeline, "_respond_with_set_reminder", "remind me") is True
    assert added == [("call Sarah", due_at)]
    assert pipeline.deliveries[0][0].startswith("Reminder set: call Sarah.")


def test_invalid_reminder_gets_actionable_prompt(monkeypatch):
    pipeline = _Pipeline()
    monkeypatch.setattr(
        responses,
        "parse_reminder_request",
        lambda text: {"message": "", "due_at": None},
    )

    assert _call(pipeline, "_respond_with_set_reminder", "remind me") is True
    assert pipeline.deliveries[0][0].startswith("I couldn't understand the reminder.")


def test_cancel_reminder_extracts_subject(monkeypatch):
    pipeline = _Pipeline()
    searches = []
    monkeypatch.setattr(
        responses,
        "cancel_reminder",
        lambda search: searches.append(search) or "cancelled",
    )

    assert _call(
        pipeline,
        "_respond_with_cancel_reminder",
        "cancel reminder about call Sarah",
    ) is True
    assert searches == ["call sarah"]
    assert pipeline.deliveries[0][0] == "cancelled"


def test_calendar_query_today_uses_date_filter(monkeypatch):
    pipeline = _Pipeline()
    dates = []
    monkeypatch.setattr(
        responses,
        "list_calendar_events",
        lambda **kwargs: dates.append(kwargs.get("date")) or ["event"],
    )
    monkeypatch.setattr(
        responses,
        "format_calendar_for_speech",
        lambda events: "one event",
    )

    assert _call(pipeline, "_respond_with_calendar_query", "what is today") is True
    assert dates[0].date() == datetime.now().date()
    assert pipeline.deliveries[0][0] == "one event"


def test_cancel_calendar_extracts_event_name(monkeypatch):
    pipeline = _Pipeline()
    searches = []
    monkeypatch.setattr(
        responses,
        "cancel_calendar_event",
        lambda search: searches.append(search) or "removed",
    )

    assert _call(
        pipeline,
        "_respond_with_cancel_calendar",
        "cancel event called dentist appointment",
    ) is True
    assert searches == ["dentist appointment"]
    assert pipeline.deliveries[0][0] == "removed"
