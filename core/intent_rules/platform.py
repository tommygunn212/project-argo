"""Deterministic platform, device, application, and clock intent rules."""

from __future__ import annotations

import re

from core.app_launch import resolve_app_launch_target
from core.app_registry import resolve_app_name
from core.intent_models import Intent, IntentType
from core.intent_system_rules import (
    AUDIO_ROUTING_KEYWORDS,
    detect_disk_query,
    detect_temperature_query,
)


BLUETOOTH_STATUS_PHRASES = [
    "bluetooth status", "is bluetooth on", "is bluetooth off", "is my bluetooth on",
    "what bluetooth devices are connected", "what devices are connected",
    "show paired bluetooth devices", "show paired devices", "show bluetooth devices",
    "list bluetooth devices", "is my headset connected", "is my headphones connected",
    "is my keyboard connected", "is my mouse connected",
]
AUDIO_ROUTING_STATUS_PHRASES = [
    "audio status", "what audio device am i using", "where is sound playing",
    "are my headphones active", "what speakers are active", "audio routing status",
]
AUDIO_ROUTING_CONTROL_PHRASES = [
    "switch to", "use", "set audio output to", "set audio input to",
    "change audio device", "change audio output", "change audio input",
]
APP_STATUS_PHRASES = [
    "is notepad open", "is notpad open", "is word running", "is excel open",
    "is chrome open", "what apps are running", "what applications are running",
    "do i have excel open", "do i have word open", "is notpad running",
    "list running applications", "list running apps",
]
APP_CONTROL_VERBS = ["open", "launch", "close", "quit", "exit", "shut down", "shutdown", "shut"]
FOCUS_STATUS_PHRASES = [
    "what app is active", "what app is in front", "what's the active window",
    "whats the active window", "what app is focused", "what app is foreground",
]
FOCUS_CONTROL_VERBS = ["focus", "bring", "switch", "activate", "make"]
VOLUME_STATUS_PHRASES = [
    "what's the volume", "whats the volume", "what is the volume", "current volume",
    "is the system muted", "is sound muted", "is the volume muted", "is volume muted",
]
VOLUME_CONTROL_PATTERNS = [
    r"\bset volume to \d{1,3}%?\b", r"\bvolume\s+\d{1,3}%?\b",
    r"\bvolume\s+to\s+\d{1,3}%?\b", r"\bvolume up\b", r"\bvolume down\b",
    r"\bturn volume up\b", r"\bturn volume down\b", r"\bincrease volume\b",
    r"\bdecrease volume\b", r"\blower volume\b", r"\blower the volume\b",
    r"\braise volume\b", r"\braise the volume\b", r"\bquieter\b", r"\blouder\b",
    r"\bmute volume\b", r"\bunmute volume\b", r"\bmute sound\b",
    r"\bunmute sound\b", r"\bmute\b", r"\bunmute\b",
]
TIME_STATUS_PHRASES = ["what time is it", "current time", "time now", "what's the time", "whats the time"]
WORLD_TIME_PATTERN = re.compile(
    r"(?:what(?:'s| is)? the time|what time is it|time|current time)\s+(?:in|at)\s+(.+?)(?:\?|$)",
    re.IGNORECASE,
)
TIME_DAY_PHRASES = ["what day is it", "what day is today", "what day is it today", "what day are we on"]
TIME_DATE_PHRASES = [
    "what's today's date", "whats today's date", "what is today's date", "what is the date",
    "what's the date", "whats the date", "today's date", "todays date", "current date",
]


def parse_platform_intent(text_original: str, text_lower: str, serious_mode: bool) -> Intent | None:
    """Return the first matching platform intent, preserving parser priority."""
    writing_guard = re.search(r"\b(email|e-mail|mail|blog|draft|note|memo|compose|article)\b", text_lower)
    vision_fs_guard = re.search(r"\b(screenshot|screen\s*shot|photos?|files?|downloads?|locate|folder)\b", text_lower)
    hw_shopping_guard = re.search(
        r"\b(latest|best|newest|buy|buying|recommend|build|building|upgrade|upgrading"
        r"|compare|comparing|vs|versus|review|benchmark|shop|shopping|market|available"
        r"|released|worth|price|cost|hotend|printer|3d|filament|nozzle|extruder"
        r"|should\s+i\s+get)\b",
        text_lower,
    )
    if not writing_guard and not vision_fs_guard and not hw_shopping_guard and detect_temperature_query(text_lower):
        return Intent(IntentType.SYSTEM_HEALTH, 1.0, text_original, serious_mode=serious_mode, subintent="temperature")

    fs_guard = re.search(r"\b(files?|downloads?|documents?|photos?|images?|videos?|find|search|locate|large|big|biggest)\b", text_lower)
    if not writing_guard and not fs_guard and detect_disk_query(text_lower):
        return Intent(IntentType.SYSTEM_HEALTH, 1.0, text_original, serious_mode=serious_mode, subintent="disk")

    explicit_toggle = any(p in text_lower for p in {"turn bluetooth on", "turn bluetooth off", "enable bluetooth", "disable bluetooth"})
    explicit_connect = re.search(r"\bconnect\b", text_lower) is not None
    explicit_disconnect = re.search(r"\bdisconnect\b", text_lower) is not None
    explicit_pair = re.search(r"\bpair\b", text_lower) is not None
    bluetooth_control = (explicit_toggle or explicit_connect or explicit_disconnect or explicit_pair) and (
        "bluetooth" in text_lower or "bt" in text_lower
        or any(term in text_lower for term in {"headset", "headphones", "earbuds", "speaker", "keyboard", "mouse"})
    )
    if bluetooth_control:
        action = None
        target = None
        if any(p in text_lower for p in {"turn bluetooth on", "enable bluetooth"}):
            action = "on"
        elif any(p in text_lower for p in {"turn bluetooth off", "disable bluetooth"}):
            action = "off"
        elif explicit_connect:
            action = "connect"
        elif explicit_disconnect:
            action = "disconnect"
        elif explicit_pair:
            action = "pair"
        if action in {"connect", "disconnect"}:
            target = re.sub(r"^(connect|disconnect)\s+(to\s+)?", "", text_lower).strip()
            target = re.sub(r"\b(bluetooth|bt)\b", "", target).strip()
        return Intent(IntentType.BLUETOOTH_CONTROL, 1.0, text_original, serious_mode=serious_mode, action=action, target=target or None)

    if any(p in text_lower for p in AUDIO_ROUTING_CONTROL_PHRASES) and any(k in text_lower for k in AUDIO_ROUTING_KEYWORDS):
        target = re.sub(r"^(switch to|use|set audio output to|set audio input to|change audio device|change audio output|change audio input)\s+", "", text_lower).strip()
        return Intent(IntentType.AUDIO_ROUTING_CONTROL, 1.0, text_original, serious_mode=serious_mode, action="switch", target=target or None)
    if any(p in text_lower for p in AUDIO_ROUTING_STATUS_PHRASES) and any(k in text_lower for k in AUDIO_ROUTING_KEYWORDS):
        return Intent(IntentType.AUDIO_ROUTING_STATUS, 1.0, text_original, serious_mode=serious_mode)

    app_status = any(p in text_lower for p in APP_STATUS_PHRASES)
    app_status_query = re.search(r"\b(is|are|do i have|what|which)\b", text_lower) and any(t in text_lower for t in {"open", "running", "apps", "applications"})
    if app_status or app_status_query:
        return Intent(IntentType.APP_STATUS, 1.0, text_original, serious_mode=serious_mode)

    if "music" not in text_lower and "song" not in text_lower:
        if any(re.search(pattern, text_lower) for pattern in VOLUME_CONTROL_PATTERNS):
            return Intent(IntentType.VOLUME_CONTROL, 1.0, text_original, serious_mode=serious_mode)
        if any(p in text_lower for p in VOLUME_STATUS_PHRASES):
            return Intent(IntentType.VOLUME_STATUS, 1.0, text_original, serious_mode=serious_mode)

    focus_status = any(p in text_lower for p in FOCUS_STATUS_PHRASES)
    focus_status_query = re.search(r"\b(is|are|what)\b", text_lower) and any(t in text_lower for t in {"focused", "active", "foreground", "in front"})
    if focus_status or focus_status_query:
        return Intent(IntentType.APP_FOCUS_STATUS, 1.0, text_original, serious_mode=serious_mode, target=resolve_app_name(text_lower) or None)
    if any(re.search(rf"\b{verb}\b", text_lower) for verb in FOCUS_CONTROL_VERBS):
        target = resolve_app_name(text_lower)
        if target:
            return Intent(IntentType.APP_FOCUS_CONTROL, 1.0, text_original, serious_mode=serious_mode, action="focus", target=target)

    world_time = WORLD_TIME_PATTERN.search(text_lower)
    if world_time and world_time.group(1).strip():
        return Intent(IntentType.WORLD_TIME, 1.0, text_original, serious_mode=serious_mode, target=world_time.group(1).strip())
    for phrases, subintent in ((TIME_STATUS_PHRASES, "time"), (TIME_DAY_PHRASES, "day"), (TIME_DATE_PHRASES, "date")):
        if any(p in text_lower for p in phrases):
            return Intent(IntentType.TIME_STATUS, 1.0, text_original, serious_mode=serious_mode, subintent=subintent)

    launch_target = resolve_app_launch_target(text_lower)
    if re.search(r"\b(open|launch|start)\b", text_lower) and launch_target:
        return Intent(IntentType.APP_LAUNCH, 1.0, text_original, serious_mode=serious_mode, action="open", target=launch_target)

    if any(re.search(rf"\b{verb}\b", text_lower) for verb in APP_CONTROL_VERBS):
        action = None
        if re.search(r"\b(open|launch)\b", text_lower):
            action = "open"
        elif re.search(r"\b(close|quit|exit|shut down|shutdown|shut)\b", text_lower):
            action = "close"
        elif re.search(r"\bfocus\b", text_lower):
            action = "focus"
        target = re.sub(r"^(open|launch|close|quit|exit|shut down|shutdown|focus)\s+", "", text_lower).strip() if action else None
        return Intent(IntentType.APP_CONTROL, 1.0, text_original, serious_mode=serious_mode, action=action, target=target or None)

    bluetooth_status = any(p in text_lower for p in BLUETOOTH_STATUS_PHRASES)
    bluetooth_implicit = ("bluetooth" in text_lower or "bt" in text_lower) and any(t in text_lower for t in {"status", "on", "off", "connected", "paired", "devices", "adapter"})
    peripheral_connected = any(t in text_lower for t in {"headset", "headphones", "earbuds", "speaker", "keyboard", "mouse"}) and "connected" in text_lower
    if bluetooth_status or bluetooth_implicit or peripheral_connected:
        return Intent(IntentType.BLUETOOTH_STATUS, 1.0, text_original, serious_mode=serious_mode)
    return None
