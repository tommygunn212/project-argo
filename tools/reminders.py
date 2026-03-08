"""
ARGO Reminders & Calendar
──────────────────────────
SQLite-backed reminder and calendar system with background checker.

Voice commands:
    "Remind me to call Sarah in 30 minutes"
    "Remind me to take medicine at 8pm"
    "Remind me tomorrow to submit the report"
    "Set a reminder for Friday at 3pm to review code"
    "What are my reminders?"
    "Cancel the reminder about Sarah"
    "Add a calendar event: dentist appointment Friday at 2pm"
    "What's on my calendar?"
    "What's on my schedule today?"
"""

import json
import logging
import re
import sqlite3
import threading
import time as _time
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("argo.reminders")

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "reminders.db"


# ── Database setup ────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            message     TEXT NOT NULL,
            due_at      TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            fired       INTEGER NOT NULL DEFAULT 0,
            cancelled   INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            start_at    TEXT NOT NULL,
            end_at      TEXT,
            location    TEXT,
            notes       TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    return conn


# ── Reminders CRUD ────────────────────────────────────────────────────

def add_reminder(message: str, due_at: datetime) -> Dict:
    """Add a reminder. Returns dict with id, message, due_at."""
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO reminders (message, due_at) VALUES (?, ?)",
            (message, due_at.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        return {
            "id": cur.lastrowid,
            "message": message,
            "due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
    finally:
        conn.close()


def list_reminders(include_fired: bool = False) -> List[Dict]:
    """List active (unfired, non-cancelled) reminders. Optionally include fired."""
    conn = _connect()
    try:
        if include_fired:
            rows = conn.execute(
                "SELECT id, message, due_at, fired, cancelled FROM reminders WHERE cancelled = 0 ORDER BY due_at"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, message, due_at, fired, cancelled FROM reminders WHERE fired = 0 AND cancelled = 0 ORDER BY due_at"
            ).fetchall()
        return [
            {"id": r[0], "message": r[1], "due_at": r[2], "fired": bool(r[3]), "cancelled": bool(r[4])}
            for r in rows
        ]
    finally:
        conn.close()


def cancel_reminder(search_text: str) -> str:
    """Cancel the first reminder whose message contains search_text."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, message FROM reminders WHERE fired = 0 AND cancelled = 0 ORDER BY due_at"
        ).fetchall()
        for rid, msg in rows:
            if search_text.lower() in msg.lower():
                conn.execute("UPDATE reminders SET cancelled = 1 WHERE id = ?", (rid,))
                conn.commit()
                return f"Cancelled reminder: {msg}"
        return f"No active reminder found matching '{search_text}'."
    finally:
        conn.close()


def get_due_reminders() -> List[Dict]:
    """Return reminders that are due now (for the background checker)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, message, due_at FROM reminders WHERE fired = 0 AND cancelled = 0 AND due_at <= ?",
            (now,),
        ).fetchall()
        results = []
        for rid, msg, due in rows:
            conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (rid,))
            results.append({"id": rid, "message": msg, "due_at": due})
        conn.commit()
        return results
    finally:
        conn.close()


# ── Calendar CRUD ─────────────────────────────────────────────────────

def add_calendar_event(title: str, start_at: datetime, end_at: Optional[datetime] = None,
                       location: str = "", notes: str = "") -> Dict:
    """Add a calendar event."""
    conn = _connect()
    try:
        end_str = end_at.strftime("%Y-%m-%d %H:%M:%S") if end_at else None
        cur = conn.execute(
            "INSERT INTO calendar_events (title, start_at, end_at, location, notes) VALUES (?, ?, ?, ?, ?)",
            (title, start_at.strftime("%Y-%m-%d %H:%M:%S"), end_str, location, notes),
        )
        conn.commit()
        return {
            "id": cur.lastrowid,
            "title": title,
            "start_at": start_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
    finally:
        conn.close()


def list_calendar_events(date: Optional[datetime] = None, days_ahead: int = 7) -> List[Dict]:
    """List upcoming calendar events. If date given, show that day only."""
    conn = _connect()
    try:
        if date:
            start = date.strftime("%Y-%m-%d 00:00:00")
            end = date.strftime("%Y-%m-%d 23:59:59")
            rows = conn.execute(
                "SELECT id, title, start_at, end_at, location FROM calendar_events "
                "WHERE start_at BETWEEN ? AND ? ORDER BY start_at",
                (start, end),
            ).fetchall()
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            future = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d %H:%M:%S")
            rows = conn.execute(
                "SELECT id, title, start_at, end_at, location FROM calendar_events "
                "WHERE start_at BETWEEN ? AND ? ORDER BY start_at",
                (now, future),
            ).fetchall()
        return [
            {"id": r[0], "title": r[1], "start_at": r[2], "end_at": r[3], "location": r[4]}
            for r in rows
        ]
    finally:
        conn.close()


def cancel_calendar_event(search_text: str) -> str:
    """Delete the first calendar event matching search_text."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, title FROM calendar_events WHERE start_at >= datetime('now','localtime') ORDER BY start_at"
        ).fetchall()
        for eid, title in rows:
            if search_text.lower() in title.lower():
                conn.execute("DELETE FROM calendar_events WHERE id = ?", (eid,))
                conn.commit()
                return f"Cancelled event: {title}"
        return f"No upcoming event found matching '{search_text}'."
    finally:
        conn.close()


# ── Voice command parser ──────────────────────────────────────────────

_RELATIVE_TIME_RE = re.compile(
    r"in\s+(\d+)\s+(minute|minutes|min|mins|hour|hours|hr|hrs|day|days|week|weeks)",
    re.IGNORECASE,
)

_ABS_TIME_RE = re.compile(
    r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?",
    re.IGNORECASE,
)

_DAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}

_RELATIVE_DAY_RE = re.compile(
    r"\b(today|tonight|tomorrow|day\s+after\s+tomorrow)\b", re.IGNORECASE,
)


def parse_reminder_request(text: str) -> Dict:
    """
    Parse a reminder voice command.
    Returns: {message: str, due_at: datetime or None}
    """
    lower = text.lower().strip()
    now = datetime.now()
    due = None
    message = ""

    # Extract "to [message]" portion
    m = re.search(r"\bto\s+(.+?)(?:\s+(?:in|at|on|by|tomorrow|today|tonight)\b|$)", lower)
    if m:
        message = m.group(1).strip()

    # If no "to" found, try extracting after "that"
    if not message:
        m = re.search(r"\bthat\s+(.+?)(?:\s+(?:in|at|on|by|tomorrow|today|tonight)\b|$)", lower)
        if m:
            message = m.group(1).strip()

    # Fallback: everything after "remind me"
    if not message:
        m = re.search(r"remind\s+me\s+(.+)", lower)
        if m:
            raw = m.group(1).strip()
            # Strip time expressions
            raw = re.sub(r"\b(?:in\s+\d+\s+\w+|at\s+\d+.*|tomorrow|today|tonight)\b", "", raw).strip()
            raw = re.sub(r"^to\s+", "", raw).strip()
            message = raw if raw else text

    if not message:
        message = text

    # Parse relative time: "in 30 minutes"
    rm = _RELATIVE_TIME_RE.search(lower)
    if rm:
        amount = int(rm.group(1))
        unit = rm.group(2).lower()
        if unit.startswith("min"):
            due = now + timedelta(minutes=amount)
        elif unit.startswith("h"):
            due = now + timedelta(hours=amount)
        elif unit.startswith("d"):
            due = now + timedelta(days=amount)
        elif unit.startswith("w"):
            due = now + timedelta(weeks=amount)

    # Parse relative day: "tomorrow", "today"
    if not due:
        dm = _RELATIVE_DAY_RE.search(lower)
        if dm:
            day_word = dm.group(1).lower()
            if day_word == "today":
                due = now.replace(hour=9, minute=0, second=0)
                if due <= now:
                    due = now + timedelta(hours=1)
            elif day_word == "tonight":
                due = now.replace(hour=20, minute=0, second=0)
                if due <= now:
                    due = now + timedelta(hours=1)
            elif day_word == "tomorrow":
                due = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0)
            elif "day after" in day_word:
                due = (now + timedelta(days=2)).replace(hour=9, minute=0, second=0)

    # Parse day name: "on Friday"
    if not due:
        for name, dow in _DAY_NAMES.items():
            if re.search(rf"\b{name}\b", lower):
                days_ahead = (dow - now.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                due = (now + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0)
                break

    # Parse absolute time and apply to due date: "at 8pm"
    am = _ABS_TIME_RE.search(lower)
    if am:
        hour = int(am.group(1))
        minute = int(am.group(2)) if am.group(2) else 0
        period = (am.group(3) or "").lower().replace(".", "")
        if period == "pm" and hour < 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0
        if due:
            due = due.replace(hour=hour, minute=minute, second=0)
        else:
            due = now.replace(hour=hour, minute=minute, second=0)
            if due <= now:
                due += timedelta(days=1)

    # Default: 1 hour from now
    if not due:
        due = now + timedelta(hours=1)

    return {"message": message.strip(" .,!?"), "due_at": due}


def parse_calendar_request(text: str) -> Dict:
    """
    Parse a calendar event voice command.
    Returns: {title: str, start_at: datetime or None, location: str}
    """
    lower = text.lower().strip()
    now = datetime.now()
    title = ""
    start = None
    location = ""

    # Extract event title
    m = re.search(r"\b(?:event|appointment|meeting)\s*[:\-]?\s*(.+?)(?:\s+(?:on|at|tomorrow|today|friday|monday|tuesday|wednesday|thursday|saturday|sunday)\b|$)", lower)
    if m:
        title = m.group(1).strip()

    # Location: "at the dentist" / "at office"
    loc_m = re.search(r"\bat\s+(?:the\s+)?([a-z][\w\s]+?)(?:\s+(?:on|at\s+\d|tomorrow|today)\b|$)", lower)
    if loc_m and not re.match(r"\d", loc_m.group(1).strip()):
        location = loc_m.group(1).strip()

    if not title:
        # Try extracting after "add" / "schedule" / "calendar"
        m = re.search(r"\b(?:add|schedule|create|put|calendar)\b.*?(?:event|appointment|meeting)?\s*[:\-]?\s*(.+)", lower)
        if m:
            raw = m.group(1).strip()
            raw = re.sub(r"\b(?:on|at)\s+(?:\d|monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today)\b.*", "", raw).strip()
            title = raw

    if not title:
        title = text

    # Parse date/time using same logic as reminders
    r = parse_reminder_request(text)
    start = r.get("due_at")

    return {"title": title.strip(" .,!?"), "start_at": start, "location": location}


# ── Spoken response formatters ────────────────────────────────────────

def format_reminders_for_speech(reminders: List[Dict]) -> str:
    """Format reminder list for spoken response."""
    if not reminders:
        return "You have no active reminders."
    lines = []
    for r in reminders:
        try:
            dt = datetime.strptime(r["due_at"], "%Y-%m-%d %H:%M:%S")
            time_str = _friendly_datetime(dt)
        except (ValueError, KeyError):
            time_str = r.get("due_at", "unknown time")
        lines.append(f"{r['message']} — {time_str}")
    if len(lines) == 1:
        return f"You have one reminder: {lines[0]}."
    return f"You have {len(lines)} reminders. " + ". ".join(lines) + "."


def format_calendar_for_speech(events: List[Dict]) -> str:
    """Format calendar events for spoken response."""
    if not events:
        return "Nothing on your calendar."
    lines = []
    for e in events:
        try:
            dt = datetime.strptime(e["start_at"], "%Y-%m-%d %H:%M:%S")
            time_str = _friendly_datetime(dt)
        except (ValueError, KeyError):
            time_str = e.get("start_at", "unknown time")
        loc = f" at {e['location']}" if e.get("location") else ""
        lines.append(f"{e['title']}{loc} — {time_str}")
    if len(lines) == 1:
        return f"You have one event: {lines[0]}."
    return f"You have {len(lines)} events. " + ". ".join(lines) + "."


def _friendly_datetime(dt: datetime) -> str:
    """Convert datetime to friendly spoken format."""
    now = datetime.now()
    delta = dt - now

    if dt.date() == now.date():
        return f"today at {dt.strftime('%I:%M %p').lstrip('0')}"
    elif dt.date() == (now + timedelta(days=1)).date():
        return f"tomorrow at {dt.strftime('%I:%M %p').lstrip('0')}"
    elif delta.days < 7:
        return f"{dt.strftime('%A')} at {dt.strftime('%I:%M %p').lstrip('0')}"
    else:
        return dt.strftime("%B %d at %I:%M %p").lstrip("0")


# ── Background reminder checker ──────────────────────────────────────

_checker_thread: Optional[threading.Thread] = None
_checker_stop = threading.Event()
_reminder_callback = None


def start_reminder_checker(callback, interval_seconds: int = 30):
    """
    Start background thread that checks for due reminders.
    callback(message: str) will be called for each due reminder.
    """
    global _checker_thread, _reminder_callback
    _reminder_callback = callback
    _checker_stop.clear()

    def _loop():
        while not _checker_stop.is_set():
            try:
                due = get_due_reminders()
                for r in due:
                    logger.info(f"[REMINDER] Firing: {r['message']}")
                    if _reminder_callback:
                        _reminder_callback(f"Reminder: {r['message']}")
            except Exception as e:
                logger.error(f"Reminder checker error: {e}")
            _checker_stop.wait(interval_seconds)

    _checker_thread = threading.Thread(target=_loop, daemon=True, name="argo-reminder-checker")
    _checker_thread.start()
    logger.info(f"Reminder checker started (interval={interval_seconds}s)")


def stop_reminder_checker():
    """Stop the background reminder checker."""
    _checker_stop.set()
    if _checker_thread:
        _checker_thread.join(timeout=5)
    logger.info("Reminder checker stopped")
