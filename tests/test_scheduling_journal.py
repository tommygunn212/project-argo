"""Reminders and calendar on the live voice, and the journal of what happened when."""

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from core import conversation_journal as J
from core import realtime_tools as T
from core.memory_store import MemoryStore
from core.realtime_tools import scheduling as S
from tools import reminders as R


@pytest.fixture
def reminder_db(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "DB_PATH", tmp_path / "reminders.db")
    return tmp_path


@pytest.fixture
def journal_db(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "JOURNAL_DB", tmp_path / "journal.db")
    return tmp_path


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "memory.db")


def _turn_on(store, day: date, hour: int, user: str, argo: str):
    turn_id = store.add_turn(user, argo)
    local = datetime(day.year, day.month, day.day, hour, 0).astimezone()
    stamp = local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(store.db_path)
    conn.execute("UPDATE conversation_turns SET timestamp = ? WHERE id = ?", (stamp, turn_id))
    conn.commit()
    conn.close()


class FakeSummarizer:
    def __init__(self, open_items=("print the second cup holder",)):
        self.calls = 0
        self.open_items = list(open_items)

    def __call__(self, system, transcript):
        self.calls += 1
        assert "data, not instructions" in system
        return json.dumps({"summary": f"Talked about: {transcript[:40]}",
                           "decisions": ["picked design two"], "open_items": self.open_items})


# --- time parsing ----------------------------------------------------------------

def test_resolve_when_reads_spoken_and_iso_times():
    now = datetime.now()
    assert abs((S.resolve_when("in 30 minutes") - now).total_seconds() - 1800) < 60
    assert S.resolve_when("2030-01-02T08:15") == datetime(2030, 1, 2, 8, 15)
    tomorrow9 = S.resolve_when("tomorrow at 9am")
    assert tomorrow9.date() == (now + timedelta(days=1)).date() and tomorrow9.hour == 9
    assert S.resolve_when("friday 3pm").hour == 15
    assert S.resolve_when("whenever") is None


def test_resolve_day_handles_the_ways_he_says_it():
    thursday = date(2026, 11, 19)  # a Thursday
    sunday = date(2026, 11, 22)
    assert J.resolve_day("yesterday", now=sunday) == date(2026, 11, 21)
    assert J.resolve_day("two days ago", now=sunday) == date(2026, 11, 20)
    assert J.resolve_day("3 days ago", now=sunday) == thursday
    assert J.resolve_day("thursday", now=sunday) == thursday
    assert J.resolve_day("last sunday", now=sunday) == date(2026, 11, 15)
    assert J.resolve_day("2026-11-01", now=sunday) == date(2026, 11, 1)
    assert J.resolve_day("a week ago", now=sunday) == date(2026, 11, 15)
    assert J.resolve_day("the blue moon", now=sunday) is None


# --- reminders and calendar ------------------------------------------------------

def test_reminder_round_trip(reminder_db):
    made = T.reminder_set("check the H2D print", "in 45 minutes")
    assert made["ok"] and "check the H2D print" == made["message"]
    listed = T.reminders_upcoming()
    assert listed["count"] == 1
    assert T.reminder_cancel("H2D")["ok"]
    assert T.reminders_upcoming()["count"] == 0


def test_past_and_unreadable_times_are_refused(reminder_db):
    assert T.reminder_set("x", "2001-01-01T09:00")["ok"] is False
    assert T.reminder_set("x", "sometime")["ok"] is False


def test_a_due_reminder_is_claimed_exactly_once(reminder_db):
    R.add_reminder("take the bread out", datetime.now() - timedelta(minutes=1))
    first, second = R.get_due_reminders(), R.get_due_reminders()
    assert [r["message"] for r in first] == ["take the bread out"] and second == []


def test_calendar_round_trip(reminder_db):
    when = (datetime.now() + timedelta(days=1)).replace(hour=14, minute=0).isoformat(timespec="minutes")
    assert T.calendar_add("dentist", when, 30, "Manhattan")["ok"]
    assert T.calendar_list("tomorrow")["count"] == 1
    assert T.calendar_list()["count"] == 1
    assert T.calendar_cancel("dentist")["ok"]


# --- journal -----------------------------------------------------------------------

def test_turns_between_uses_local_day_bounds(store):
    day = date(2026, 11, 20)
    _turn_on(store, day, 1, "early", "a")      # 1am local still belongs to the 20th
    _turn_on(store, day, 23, "late", "b")
    _turn_on(store, day + timedelta(days=1), 10, "next day", "c")
    start, end = J._utc_bounds(day)
    assert [t.user_text for t in store.turns_between(start, end)] == ["early", "late"]


def test_digest_is_made_once_and_remade_when_turns_change(store, journal_db):
    day = date(2026, 11, 20)
    _turn_on(store, day, 10, "let's print the cup holder", "design two looks best")
    fake = FakeSummarizer()
    first = J.day_digest(day, store=store, summarizer=fake)
    again = J.day_digest(day, store=store, summarizer=fake)
    assert fake.calls == 1 and first["summary"] == again["summary"]
    assert first["open_items"] == ["print the second cup holder"]
    _turn_on(store, day, 11, "one more thing", "sure")
    J.day_digest(day, store=store, summarizer=fake)
    assert fake.calls == 2


def test_recap_of_a_quiet_day_points_to_the_last_real_one(store, journal_db, monkeypatch):
    monkeypatch.setattr(J, "today", lambda: date(2026, 11, 22))
    _turn_on(store, date(2026, 11, 19), 10, "hi", "hello")
    result = J.recap("yesterday", store=store, summarizer=FakeSummarizer())
    assert result["found"] is False and "Thursday" in result["message"]
    found = J.recap("thursday", store=store, summarizer=FakeSummarizer())
    assert found["found"] is True and found["decisions"] == ["picked design two"]


def test_pending_drops_items_marked_done(store, journal_db, reminder_db, monkeypatch):
    monkeypatch.setattr(J, "today", lambda: date(2026, 11, 22))
    _turn_on(store, date(2026, 11, 21), 10, "x", "y")
    fake = FakeSummarizer(open_items=["re-add the Feit lights in Home Assistant",
                                      "turn off the bedroom lights at night"])
    before = J.pending(store=store, summarizer=fake)["open_items"]
    assert len(before) == 2
    J.mark_done("Feit lights re-added")
    after = [i["item"] for i in J.pending(store=store, summarizer=fake)["open_items"]]
    # Only the Feit item clears; sharing the word "lights" is not enough.
    assert after == ["turn off the bedroom lights at night"]


def test_briefing_has_every_section(store, journal_db, reminder_db, monkeypatch):
    monkeypatch.setattr(J, "today", lambda: datetime.now().date())
    _turn_on(store, datetime.now().date() - timedelta(days=1), 10, "x", "y")
    R.add_reminder("call the vet", datetime.now() + timedelta(hours=2))
    brief = J.briefing(store=store, summarizer=FakeSummarizer())
    for key in ("now", "today_calendar", "reminders", "last_time", "open_items",
                "background_jobs", "not_connected_yet"):
        assert key in brief
    assert brief["reminders"][0]["message"] == "call the vet"
    assert brief["last_time"]["found"] is True


def test_the_agent_exposes_scheduling_and_journal_tools():
    import livekit_realtime_agent as agent_mod

    for name in ("what_time_is_it", "set_reminder", "list_reminders", "cancel_reminder",
                 "add_calendar_event", "list_calendar", "cancel_calendar_event",
                 "where_we_left_off", "whats_pending", "mark_pending_done", "morning_briefing"):
        assert hasattr(agent_mod.ArgoRealtimeAgent, name), name
