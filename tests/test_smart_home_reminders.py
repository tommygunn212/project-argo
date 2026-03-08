"""
Tests for ARGO Home Assistant integration (tools/home_assistant.py)
and Reminders/Calendar system (tools/reminders.py).
"""

import os
import sys
import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── Ensure project root on path ────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ====================================================================
# HOME ASSISTANT TESTS
# ====================================================================

from tools.home_assistant import (
    parse_smart_home_command,
    resolve_entity,
    _infer_domain,
    is_home_assistant_configured,
)


class TestSmartHomeParser:
    """Test voice command parsing for smart home actions."""

    def test_turn_on_lights(self):
        r = parse_smart_home_command("turn on the living room lights")
        assert r["action"] == "turn_on"
        assert "living room lights" in r["device"]

    def test_turn_off_tv(self):
        r = parse_smart_home_command("turn off the TV")
        assert r["action"] == "turn_off"
        assert "tv" in r["device"].lower()

    def test_toggle(self):
        r = parse_smart_home_command("toggle the bedroom fan")
        assert r["action"] == "toggle"
        assert "bedroom fan" in r["device"]

    def test_switch_on(self):
        r = parse_smart_home_command("switch on the kitchen light")
        assert r["action"] == "turn_on"
        assert "kitchen light" in r["device"]

    def test_device_on_shorthand(self):
        r = parse_smart_home_command("lights on")
        assert r["action"] == "turn_on"
        assert "light" in r["device"].lower()

    def test_set_thermostat(self):
        r = parse_smart_home_command("set thermostat to 72")
        assert r["action"] == "set_temperature"
        assert r["value"] == 72.0
        assert r["domain"] == "climate"

    def test_set_ac_cool(self):
        r = parse_smart_home_command("set the AC to 68")
        assert r["action"] == "set_temperature"
        assert r["value"] == 68.0
        assert r["mode"] == "cool"

    def test_set_heat(self):
        r = parse_smart_home_command("set the heat to 74")
        assert r["action"] == "set_temperature"
        assert r["value"] == 74.0
        assert r["mode"] == "heat"

    def test_set_brightness(self):
        r = parse_smart_home_command("dim the bedroom light to 30%")
        assert r["action"] == "set_brightness"
        assert r["value"] == 30
        assert r["domain"] == "light"

    def test_set_color(self):
        r = parse_smart_home_command("set the living room light to blue")
        assert r["action"] == "set_color"
        assert r["value"] == "blue"

    def test_scene_activation(self):
        r = parse_smart_home_command("activate the movie night scene")
        assert r["action"] == "activate_scene"
        assert "movie night" in r["device"]

    def test_lock(self):
        r = parse_smart_home_command("lock the front door")
        assert r["action"] == "lock"
        assert "front door" in r["device"]

    def test_unlock(self):
        r = parse_smart_home_command("unlock the front door")
        assert r["action"] == "unlock"
        assert "front door" in r["device"]

    def test_status_query(self):
        r = parse_smart_home_command("status of the thermostat")
        assert r["action"] == "status"

    def test_is_light_on(self):
        r = parse_smart_home_command("is the kitchen light on")
        assert r["action"] == "status"

    def test_list_devices(self):
        r = parse_smart_home_command("list my smart home devices")
        assert r["action"] == "list_devices"

    def test_list_lights(self):
        r = parse_smart_home_command("show me all lights")
        assert r["action"] == "list_devices"
        assert r["domain"] == "light"

    def test_empty_command(self):
        r = parse_smart_home_command("")
        assert r["action"] is None

    def test_unrelated_text(self):
        r = parse_smart_home_command("what's the weather today")
        assert r["action"] is None


class TestDomainInference:
    """Test _infer_domain helper."""

    def test_light_domain(self):
        r = {"device": "kitchen light"}
        _infer_domain(r)
        assert r["domain"] == "light"

    def test_tv_domain(self):
        r = {"device": "samsung tv"}
        _infer_domain(r)
        assert r["domain"] == "media_player"

    def test_thermostat_domain(self):
        r = {"device": "upstairs thermostat"}
        _infer_domain(r)
        assert r["domain"] == "climate"

    def test_fan_domain(self):
        r = {"device": "ceiling fan"}
        _infer_domain(r)
        assert r["domain"] == "fan"

    def test_lock_domain(self):
        r = {"device": "front door lock"}
        _infer_domain(r)
        assert r["domain"] == "lock"

    def test_garage_domain(self):
        r = {"device": "garage door"}
        _infer_domain(r)
        assert r["domain"] == "cover"


class TestHAConfig:
    """Test Home Assistant configuration detection."""

    def test_not_configured_empty(self):
        with patch("tools.home_assistant._load_ha_config", return_value={}):
            assert is_home_assistant_configured() is False

    def test_not_configured_no_token(self):
        with patch("tools.home_assistant._load_ha_config", return_value={"url": "http://ha.local:8123"}):
            assert is_home_assistant_configured() is False

    def test_configured(self):
        with patch("tools.home_assistant._load_ha_config", return_value={
            "url": "http://ha.local:8123",
            "token": "abc123",
        }):
            assert is_home_assistant_configured() is True


# ====================================================================
# REMINDERS TESTS
# ====================================================================

from tools.reminders import (
    add_reminder,
    list_reminders,
    cancel_reminder,
    get_due_reminders,
    add_calendar_event,
    list_calendar_events,
    cancel_calendar_event,
    parse_reminder_request,
    parse_calendar_request,
    format_reminders_for_speech,
    format_calendar_for_speech,
    _connect,
    DB_PATH,
)


@pytest.fixture(autouse=True)
def _use_temp_db(tmp_path, monkeypatch):
    """Redirect reminders DB to a temp directory for each test."""
    temp_db = tmp_path / "test_reminders.db"
    monkeypatch.setattr("tools.reminders.DB_PATH", temp_db)


class TestReminderParser:
    """Test parse_reminder_request voice command parsing."""

    def test_in_30_minutes(self):
        r = parse_reminder_request("remind me to call Sarah in 30 minutes")
        assert "call sarah" in r["message"].lower()
        delta = r["due_at"] - datetime.now()
        assert 25 * 60 < delta.total_seconds() < 35 * 60

    def test_in_2_hours(self):
        r = parse_reminder_request("remind me to take medicine in 2 hours")
        delta = r["due_at"] - datetime.now()
        assert 1.9 * 3600 < delta.total_seconds() < 2.1 * 3600

    def test_tomorrow(self):
        r = parse_reminder_request("remind me tomorrow to submit the report")
        assert r["due_at"].date() == (datetime.now() + timedelta(days=1)).date()

    def test_at_8pm(self):
        r = parse_reminder_request("remind me to take medicine at 8pm")
        assert r["due_at"].hour == 20
        assert r["due_at"].minute == 0

    def test_at_3_30_am(self):
        r = parse_reminder_request("remind me at 3:30 am to check the server")
        assert r["due_at"].hour == 3
        assert r["due_at"].minute == 30

    def test_default_1_hour(self):
        r = parse_reminder_request("remind me to buy milk")
        delta = r["due_at"] - datetime.now()
        assert 55 * 60 < delta.total_seconds() < 65 * 60

    def test_message_extraction_with_to(self):
        r = parse_reminder_request("remind me to call the dentist in 1 hour")
        assert "call the dentist" in r["message"].lower()

    def test_message_extraction_with_that(self):
        r = parse_reminder_request("remind me that the meeting is at 3pm")
        assert "meeting" in r["message"].lower()


class TestReminderCRUD:
    """Test reminder database operations."""

    def test_add_and_list(self):
        due = datetime.now() + timedelta(hours=1)
        add_reminder("test reminder", due)
        reminders = list_reminders()
        assert len(reminders) == 1
        assert reminders[0]["message"] == "test reminder"

    def test_multiple_reminders_ordered(self):
        add_reminder("later", datetime.now() + timedelta(hours=2))
        add_reminder("sooner", datetime.now() + timedelta(minutes=30))
        reminders = list_reminders()
        assert len(reminders) == 2
        assert reminders[0]["message"] == "sooner"

    def test_cancel_reminder(self):
        add_reminder("call sarah", datetime.now() + timedelta(hours=1))
        add_reminder("buy milk", datetime.now() + timedelta(hours=2))
        result = cancel_reminder("sarah")
        assert "call sarah" in result.lower()
        reminders = list_reminders()
        assert len(reminders) == 1
        assert reminders[0]["message"] == "buy milk"

    def test_cancel_nonexistent(self):
        result = cancel_reminder("nonexistent thing")
        assert "no active reminder" in result.lower()

    def test_due_reminders(self):
        # Add one that's already past due
        past = datetime.now() - timedelta(minutes=5)
        add_reminder("overdue reminder", past)
        due = get_due_reminders()
        assert len(due) == 1
        assert due[0]["message"] == "overdue reminder"
        # After firing, it shouldn't appear again
        due2 = get_due_reminders()
        assert len(due2) == 0

    def test_fired_not_in_active_list(self):
        past = datetime.now() - timedelta(minutes=5)
        add_reminder("fired one", past)
        get_due_reminders()  # fire it
        reminders = list_reminders(include_fired=False)
        assert len(reminders) == 0

    def test_fired_in_full_list(self):
        past = datetime.now() - timedelta(minutes=5)
        add_reminder("fired one", past)
        get_due_reminders()  # fire it
        reminders = list_reminders(include_fired=True)
        assert len(reminders) == 1


class TestCalendarCRUD:
    """Test calendar event operations."""

    def test_add_and_list(self):
        start = datetime.now() + timedelta(hours=2)
        add_calendar_event("Dentist", start)
        events = list_calendar_events()
        assert len(events) == 1
        assert events[0]["title"] == "Dentist"

    def test_add_with_location(self):
        start = datetime.now() + timedelta(hours=3)
        add_calendar_event("Meeting", start, location="Office")
        events = list_calendar_events()
        assert events[0]["location"] == "Office"

    def test_list_today_only(self):
        today = datetime.now().replace(hour=23, minute=0, second=0)
        tomorrow = datetime.now() + timedelta(days=1)
        add_calendar_event("Today event", today)
        add_calendar_event("Tomorrow event", tomorrow)
        events = list_calendar_events(date=datetime.now())
        assert len(events) == 1
        assert events[0]["title"] == "Today event"

    def test_cancel_event(self):
        start = datetime.now() + timedelta(hours=1)
        add_calendar_event("Dentist appointment", start)
        result = cancel_calendar_event("dentist")
        assert "dentist" in result.lower()
        events = list_calendar_events()
        assert len(events) == 0

    def test_cancel_nonexistent(self):
        result = cancel_calendar_event("fake event")
        assert "no upcoming event" in result.lower()


class TestCalendarParser:
    """Test calendar voice command parsing."""

    def test_basic_event(self):
        r = parse_calendar_request("add a calendar event dentist appointment Friday at 2pm")
        assert "dentist" in r["title"].lower()
        assert r["start_at"] is not None

    def test_meeting_event(self):
        r = parse_calendar_request("schedule a meeting with Paul tomorrow at 10am")
        assert r["start_at"] is not None
        assert r["start_at"].hour == 10


class TestSpeechFormatters:
    """Test spoken output formatting."""

    def test_no_reminders(self):
        assert "no active reminders" in format_reminders_for_speech([]).lower()

    def test_one_reminder(self):
        r = [{"message": "call Sarah", "due_at": (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")}]
        result = format_reminders_for_speech(r)
        assert "one reminder" in result.lower()
        assert "call sarah" in result.lower()

    def test_multiple_reminders(self):
        now = datetime.now()
        r = [
            {"message": "call Sarah", "due_at": (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")},
            {"message": "buy milk", "due_at": (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")},
        ]
        result = format_reminders_for_speech(r)
        assert "2 reminders" in result

    def test_no_calendar_events(self):
        assert "nothing on your calendar" in format_calendar_for_speech([]).lower()

    def test_one_event(self):
        e = [{"title": "Dentist", "start_at": (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), "location": ""}]
        result = format_calendar_for_speech(e)
        assert "one event" in result.lower()
        assert "dentist" in result.lower()

    def test_event_with_location(self):
        e = [{"title": "Meeting", "start_at": (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), "location": "Office"}]
        result = format_calendar_for_speech(e)
        assert "office" in result.lower()


# ====================================================================
# INTENT PARSER INTEGRATION TESTS
# ====================================================================

from core.intent_parser import RuleBasedIntentParser, IntentType


class TestSmartHomeIntents:
    """Verify smart home commands are parsed to correct intent types."""

    @pytest.fixture(autouse=True)
    def _parser(self):
        self.parser = RuleBasedIntentParser()

    def test_turn_on_lights(self):
        intent = self.parser.parse("turn on the living room lights")
        assert intent.intent_type == IntentType.SMART_HOME_CONTROL

    def test_turn_off_tv(self):
        intent = self.parser.parse("turn off the TV")
        assert intent.intent_type == IntentType.SMART_HOME_CONTROL

    def test_set_thermostat(self):
        intent = self.parser.parse("set thermostat to 72")
        assert intent.intent_type == IntentType.SMART_HOME_CONTROL

    def test_activate_scene(self):
        intent = self.parser.parse("activate the movie night scene")
        assert intent.intent_type == IntentType.SMART_HOME_CONTROL

    def test_list_smart_devices(self):
        intent = self.parser.parse("list my smart home devices")
        assert intent.intent_type == IntentType.SMART_HOME_CONTROL

    def test_light_status(self):
        intent = self.parser.parse("status of the kitchen light")
        assert intent.intent_type == IntentType.SMART_HOME_STATUS


class TestReminderIntents:
    """Verify reminder commands are parsed to correct intent types."""

    @pytest.fixture(autouse=True)
    def _parser(self):
        self.parser = RuleBasedIntentParser()

    def test_remind_me(self):
        intent = self.parser.parse("remind me to call Sarah in 30 minutes")
        assert intent.intent_type == IntentType.SET_REMINDER

    def test_set_reminder(self):
        intent = self.parser.parse("set a reminder for 3pm to check the build")
        assert intent.intent_type == IntentType.SET_REMINDER

    def test_list_reminders(self):
        intent = self.parser.parse("what are my reminders")
        assert intent.intent_type == IntentType.LIST_REMINDERS

    def test_show_reminders(self):
        intent = self.parser.parse("show my reminders")
        assert intent.intent_type == IntentType.LIST_REMINDERS

    def test_cancel_reminder(self):
        intent = self.parser.parse("cancel the reminder about Sarah")
        assert intent.intent_type == IntentType.CANCEL_REMINDER


class TestCalendarIntents:
    """Verify calendar commands are parsed to correct intent types."""

    @pytest.fixture(autouse=True)
    def _parser(self):
        self.parser = RuleBasedIntentParser()

    def test_add_event(self):
        intent = self.parser.parse("add a calendar event dentist Friday at 2pm")
        assert intent.intent_type == IntentType.CALENDAR_ADD

    def test_schedule_meeting(self):
        intent = self.parser.parse("schedule a meeting with Paul tomorrow")
        assert intent.intent_type == IntentType.CALENDAR_ADD

    def test_whats_on_calendar(self):
        intent = self.parser.parse("what's on my calendar today")
        assert intent.intent_type == IntentType.CALENDAR_QUERY

    def test_show_schedule(self):
        intent = self.parser.parse("show my schedule for today")
        assert intent.intent_type == IntentType.CALENDAR_QUERY

    def test_cancel_event(self):
        intent = self.parser.parse("cancel the dentist appointment")
        assert intent.intent_type == IntentType.CANCEL_CALENDAR


# ====================================================================
# NON-REGRESSION: verify existing intents aren't stolen
# ====================================================================

class TestNoRegression:
    """Make sure the new rules don't steal existing intent classifications."""

    @pytest.fixture(autouse=True)
    def _parser(self):
        self.parser = RuleBasedIntentParser()

    def test_cpu_temp_not_smart_home(self):
        """Temperature queries about CPU should NOT route to smart home."""
        intent = self.parser.parse("what's the CPU temperature")
        assert intent.intent_type != IntentType.SMART_HOME_CONTROL
        assert intent.intent_type != IntentType.SMART_HOME_STATUS

    def test_system_status_not_smart_home(self):
        intent = self.parser.parse("give me a system status")
        assert intent.intent_type in (IntentType.SYSTEM_STATUS, IntentType.SYSTEM_HEALTH)

    def test_volume_not_smart_home(self):
        intent = self.parser.parse("set volume to 50 percent")
        assert intent.intent_type == IntentType.VOLUME_CONTROL

    def test_bluetooth_not_smart_home(self):
        intent = self.parser.parse("turn bluetooth on")
        assert intent.intent_type == IntentType.BLUETOOTH_CONTROL

    def test_email_not_reminder(self):
        intent = self.parser.parse("write an email to Paul")
        assert intent.intent_type == IntentType.WRITE_EMAIL

    def test_music_not_affected(self):
        intent = self.parser.parse("play some jazz")
        assert intent.intent_type == IntentType.MUSIC
