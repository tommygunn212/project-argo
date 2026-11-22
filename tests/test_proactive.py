"""core/voice/proactive.py: ARGO speaks first for due reminders and the morning offer."""

import asyncio
from datetime import datetime, timedelta

from core.voice import proactive as P


class FakeSession:
    def __init__(self):
        self.said = []

    def generate_reply(self, instructions, allow_interruptions=True):
        self.said.append(instructions)


def test_due_reminders_are_spoken(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "BRIEFING_MARKER", tmp_path / "marker.txt")
    monkeypatch.setattr(P.voice_events, "emit", lambda *a, **k: None)
    session, stop = FakeSession(), asyncio.Event()
    batches = [[{"id": 1, "message": "check the oven",
                 "due_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}], []]

    def due():
        batch = batches.pop(0) if batches else []
        if not batches:
            stop.set()
        return batch

    settings = P.ProactiveSettings(interval_s=5, morning_offer=False)
    asyncio.run(asyncio.wait_for(P.run_loop(session, settings, due=due, stop=stop), 10))
    assert len(session.said) == 1 and "check the oven" in session.said[0]
    assert "late" not in session.said[0]


def test_an_old_reminder_is_called_late():
    due = (datetime.now() - timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M:%S")
    text = P.reminder_instruction({"message": "x", "due_at": due})
    assert "late reminder" in text


def test_morning_offer_once_per_day(tmp_path):
    marker = tmp_path / "m.txt"
    morning = datetime.now().replace(hour=8)
    assert P.morning_offer_due(morning, marker)
    P._mark_morning_offer(morning, marker)
    assert not P.morning_offer_due(morning, marker)
    assert not P.morning_offer_due(datetime.now().replace(hour=3), tmp_path / "other.txt")


def test_the_loop_survives_a_failing_check(monkeypatch, tmp_path):
    monkeypatch.setattr(P.voice_events, "emit", lambda *a, **k: None)
    session, stop, calls = FakeSession(), asyncio.Event(), []

    def due():
        calls.append(1)
        if len(calls) >= 2:
            stop.set()
            return []
        raise RuntimeError("database locked")

    settings = P.ProactiveSettings(interval_s=5, morning_offer=False)
    P.ProactiveSettings.__init__  # noqa: B018
    asyncio.run(asyncio.wait_for(P.run_loop(session, settings, due=due, stop=stop), 15))
    assert len(calls) == 2


def test_switch_off(monkeypatch):
    monkeypatch.setenv("ARGO_PROACTIVE", "0")
    assert P.load_settings({}).enabled is False
    assert P.start_proactive(object(), FakeSession()) is None
