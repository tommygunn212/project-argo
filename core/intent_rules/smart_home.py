"""Smart-home intent rules."""

from __future__ import annotations

import re

from core.intent_models import Intent, IntentType


def parse_smart_home_intent(text_original: str, text_lower: str, serious_mode: bool) -> Intent | None:
    # ── Smart Home ──────────────────────────────────────────────

    # SMART_HOME_STATUS: "is the living room light on", "status of the thermostat"
    if re.search(r"\b(status|state|check)\b.*\b(lights?|lamps?|switches?|plugs?|fans?|thermostats?|ac|tvs?|locks?|blinds?|smart\s*home)\b", text_lower) or \
       (re.search(r"\bis\s+(?:the\s+)?\w+.+?\s+(on|off|open|closed|locked|unlocked)\b", text_lower) and \
       re.search(r"\b(lights?|lamps?|switches?|fans?|thermostats?|ac|tvs?|locks?|blinds?|doors?|garage)\b", text_lower)):
        return Intent(
            intent_type=IntentType.SMART_HOME_STATUS,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # SMART_HOME_CONTROL: "turn on the lights", "set thermostat to 72", "dim the bedroom"
    if re.search(r"\b(turn\s+on|turn\s+off|switch\s+on|switch\s+off|toggle|dim|brighten)\b.*\b(lights?|lamps?|switches?|plugs?|fans?|tvs?|thermostats?|ac|blinds?|garage|smart|bulbs?|strips?)\b", text_lower) or \
       re.search(r"\bset\s+(?:the\s+)?(?:thermostat|ac|a\.?c|temperature|heat)\b", text_lower) or \
       re.search(r"\b(?:lights?|lamps?|bulbs?|switches?|fans?|tvs?|plugs?)\s+(on|off)\b", text_lower) or \
       re.search(r"\b(activate|trigger)\b.*\bscene\b", text_lower) or \
       (re.search(r"\b(lock|unlock)\s+(?:the\s+)?\w+", text_lower) and \
       re.search(r"\b(door|lock|deadbolt|front|back|garage)\b", text_lower)) or \
       re.search(r"\b(list|show)\b.*\b(devices?|smart\s*home|lights?|switches?)\b", text_lower):
        return Intent(
            intent_type=IntentType.SMART_HOME_CONTROL,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    return None
