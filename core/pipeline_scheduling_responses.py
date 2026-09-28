"""Reminder and calendar responses for the classic pipeline."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Protocol

from tools.reminders import (
    add_calendar_event,
    add_reminder,
    cancel_calendar_event,
    cancel_reminder,
    format_calendar_for_speech,
    format_reminders_for_speech,
    list_calendar_events,
    list_reminders,
    parse_calendar_request,
    parse_reminder_request,
)


class PipelineSchedulingResponseMixin:
    # ── Reminder handlers ───────────────────────────────────────────

    def _respond_with_set_reminder(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Set a new reminder from voice command."""
        self.logger.info(f"[REMINDER] Set: {user_text}")
        parsed = parse_reminder_request(user_text)
        message = parsed.get("message", "")
        due_at = parsed.get("due_at")
        if not message or not due_at:
            return self._deliver_canonical_response(
                "I couldn't understand the reminder. Try: remind me to call Sarah in 30 minutes.",
                interaction_id, replay_mode, overrides,
            )
        result = add_reminder(message, due_at)
        friendly_time = due_at.strftime("%I:%M %p").lstrip("0")
        if due_at.date() == datetime.now().date():
            time_desc = f"today at {friendly_time}"
        elif due_at.date() == (datetime.now() + timedelta(days=1)).date():
            time_desc = f"tomorrow at {friendly_time}"
        else:
            time_desc = due_at.strftime("%A %B %d at %I:%M %p").lstrip("0")
        response = f"Reminder set: {message}. I'll remind you {time_desc}."
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_list_reminders(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """List active reminders."""
        self.logger.info(f"[REMINDER] List: {user_text}")
        reminders = list_reminders()
        response = format_reminders_for_speech(reminders)
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_cancel_reminder(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Cancel a reminder matching spoken text."""
        self.logger.info(f"[REMINDER] Cancel: {user_text}")
        # Extract the search term after "cancel reminder about..."
        import re as _re
        m = _re.search(r"\b(?:cancel|delete|remove)\b.*?\breminder\b\s*(?:about|for|to)?\s*(.+)", user_text.lower())
        search = m.group(1).strip(" .,!?") if m else user_text
        response = cancel_reminder(search)
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    # ── Calendar handlers ───────────────────────────────────────────

    def _respond_with_calendar_add(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Add a calendar event from voice command."""
        self.logger.info(f"[CALENDAR] Add: {user_text}")
        parsed = parse_calendar_request(user_text)
        title = parsed.get("title", "")
        start_at = parsed.get("start_at")
        location = parsed.get("location", "")
        if not title or not start_at:
            return self._deliver_canonical_response(
                "I couldn't parse the event. Try: add a calendar event dentist appointment Friday at 2pm.",
                interaction_id, replay_mode, overrides,
            )
        result = add_calendar_event(title, start_at, location=location)
        friendly_time = start_at.strftime("%A %B %d at %I:%M %p").lstrip("0")
        response = f"Event added: {title}, {friendly_time}."
        if location:
            response = f"Event added: {title} at {location}, {friendly_time}."
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_calendar_query(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """List upcoming calendar events."""
        self.logger.info(f"[CALENDAR] Query: {user_text}")
        lower = user_text.lower()
        if "today" in lower:
            events = list_calendar_events(date=datetime.now())
        elif "tomorrow" in lower:
            events = list_calendar_events(date=datetime.now() + timedelta(days=1))
        else:
            events = list_calendar_events()
        response = format_calendar_for_speech(events)
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_cancel_calendar(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Cancel a calendar event matching spoken text."""
        self.logger.info(f"[CALENDAR] Cancel: {user_text}")
        m = re.search(r"\b(?:cancel|delete|remove)\b.*?\b(?:event|appointment|meeting)\b\s*(?:about|for|called)?\s*(.+)", user_text.lower())
        search = m.group(1).strip(" .,!?") if m else user_text
        response = cancel_calendar_event(search)
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)


class SchedulingResponseHost(Protocol):
    """Small host contract required by reminder and calendar responses."""

    logger: Any

    def _deliver_canonical_response(self, message: str, *args: Any, **kwargs: Any) -> bool: ...


class PipelineSchedulingService(PipelineSchedulingResponseMixin):
    """Composed scheduling handlers backed by a narrow pipeline interface."""

    def __init__(self, host: SchedulingResponseHost):
        self._host = host

    @property
    def logger(self) -> Any:
        return self._host.logger

    def _deliver_canonical_response(self, message: str, *args: Any, **kwargs: Any) -> bool:
        return self._host._deliver_canonical_response(message, *args, **kwargs)

