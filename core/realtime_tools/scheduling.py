"""Reminders, calendar, and the journal of what happened when.

Reminders and calendar events live in tools/reminders.py (SQLite at
data/reminders.db), which until now only the classic pipeline could reach.
The journal (core.conversation_journal) answers questions by time: where we
left off on a given day, what is still pending, the morning briefing.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from core import conversation_journal as journal
from core.realtime_tools._base import capability

__all__ = [
    "now_local", "reminder_set", "reminders_upcoming", "reminder_cancel",
    "calendar_add", "calendar_list", "calendar_cancel",
    "conversation_recap", "pending_items", "pending_done", "daily_briefing",
]


def _reminders():
    from tools import reminders

    return reminders


def resolve_when(when: str, *, now: datetime | None = None) -> datetime | None:
    """ISO ("2026-11-22T20:00"), "in 30 minutes", "tomorrow at 9am", "friday 3pm"..."""
    now = now or datetime.now()
    text = (when or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", ""))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    lowered = text.lower()
    if not re.search(r"\d|today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|"
                     r"saturday|sunday|noon|midnight", lowered):
        return None
    lowered = lowered.replace("noon", "at 12pm").replace("midnight", "at 12am")
    if re.fullmatch(r"\d{1,2}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.)", lowered):
        lowered = "at " + lowered
    lowered = re.sub(r"(?<!at )\b(\d{1,2}(:\d{2})?\s*(am|pm))\b", r"at \1", lowered)
    return _reminders().parse_reminder_request(f"remind me to x {lowered}")["due_at"]


def _spoken(dt: datetime) -> str:
    try:
        return _reminders()._friendly_datetime(dt)
    except Exception:
        return dt.strftime("%A %I:%M %p")


@capability
def now_local() -> dict:
    """The local date and time, so relative times can be worked out exactly."""
    now = datetime.now()
    return {"ok": True, "iso": now.isoformat(timespec="minutes"),
            "spoken": now.strftime("%A, %B %d %Y, %I:%M %p").replace(" 0", " ")}


@capability
def reminder_set(message: str, when: str) -> dict:
    due = resolve_when(when)
    if due is None:
        return {"ok": False, "error": f"Couldn't read the time '{when}'. Give a time like "
                                      "'in 20 minutes', 'tomorrow at 9am' or an ISO time."}
    if due <= datetime.now() - timedelta(minutes=1):
        return {"ok": False, "error": f"That time ({_spoken(due)}) has already passed."}
    saved = _reminders().add_reminder(message.strip(), due)
    return {"ok": True, "id": saved["id"], "message": saved["message"], "due": _spoken(due),
            "due_iso": due.isoformat(timespec="minutes")}


@capability
def reminders_upcoming() -> dict:
    items = _reminders().list_reminders()
    return {"ok": True, "count": len(items),
            "reminders": [{"message": r["message"], "due": r["due_at"]} for r in items[:20]]}


@capability
def reminder_cancel(match: str) -> dict:
    message = _reminders().cancel_reminder(match)
    return {"ok": not message.startswith("No "), "message": message}


@capability
def calendar_add(title: str, when: str, duration_minutes: int = 60, location: str = "") -> dict:
    start = resolve_when(when)
    if start is None:
        return {"ok": False, "error": f"Couldn't read the time '{when}'."}
    end = start + timedelta(minutes=max(0, int(duration_minutes or 0))) if duration_minutes else None
    saved = _reminders().add_calendar_event(title.strip(), start, end, location=location)
    return {"ok": True, "id": saved["id"], "title": saved["title"], "starts": _spoken(start)}


@capability
def calendar_list(day: str = "", days_ahead: int = 7) -> dict:
    target = journal.resolve_day(day) if day else None
    if day and target is None:
        # "next friday" and other future references: let the time parser try.
        when = resolve_when(day)
        target = when.date() if when else None
    events = _reminders().list_calendar_events(
        date=datetime.combine(target, datetime.min.time()) if target else None,
        days_ahead=int(days_ahead or 7))
    return {"ok": True, "count": len(events), "events": events}


@capability
def calendar_cancel(match: str) -> dict:
    message = _reminders().cancel_calendar_event(match)
    return {"ok": not message.startswith("No "), "message": message}


@capability
def conversation_recap(when: str = "yesterday") -> dict:
    return journal.recap(when)


@capability
def pending_items() -> dict:
    return journal.pending()


@capability
def pending_done(item: str) -> dict:
    return journal.mark_done(item)


@capability
def daily_briefing() -> dict:
    return journal.briefing()
