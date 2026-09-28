"""Reminder and calendar intent rules."""

from __future__ import annotations

import re

from core.intent_models import Intent, IntentType


def parse_scheduling_intent(text_original: str, text_lower: str, serious_mode: bool) -> Intent | None:
    # ── Reminders ──────────────────────────────────────────────

    # CANCEL_REMINDER: "cancel the reminder about Sarah"
    if re.search(r"\b(cancel|delete|remove)\b.*\breminder\b", text_lower):
        return Intent(
            intent_type=IntentType.CANCEL_REMINDER,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # SET_REMINDER: "remind me to…", "set a reminder…"
    if re.search(r"\bremind\s+me\b", text_lower) or \
       re.search(r"\bset\s+(?:a\s+)?reminder\b", text_lower):
        return Intent(
            intent_type=IntentType.SET_REMINDER,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # LIST_REMINDERS: "what are my reminders", "show reminders", "any reminders"
    if re.search(r"\b(list|show|what|any)\b.*\breminders?\b", text_lower):
        return Intent(
            intent_type=IntentType.LIST_REMINDERS,
            confidence=0.95,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # ── Calendar ───────────────────────────────────────────────

    # CANCEL_CALENDAR: "cancel the dentist appointment"
    if re.search(r"\b(cancel|delete|remove)\b.*\b(event|appointment|meeting)\b", text_lower):
        return Intent(
            intent_type=IntentType.CANCEL_CALENDAR,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # CALENDAR_ADD: "add a calendar event", "schedule a meeting"
    if re.search(r"\b(add|schedule|create|put|book)\b.*\b(event|appointment|meeting|calendar)\b", text_lower):
        return Intent(
            intent_type=IntentType.CALENDAR_ADD,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # CALENDAR_QUERY: "what's on my calendar", "schedule for today"
    if re.search(r"\b(what|show|any|check)\b.*\b(calendar|schedule|agenda)\b", text_lower) or \
       re.search(r"\bschedule\s+(?:for\s+)?(?:today|tomorrow|this\s+week)\b", text_lower):
        return Intent(
            intent_type=IntentType.CALENDAR_QUERY,
            confidence=0.95,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    return None
