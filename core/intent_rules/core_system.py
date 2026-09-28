"""Deterministic ARGO identity, governance, and system-information rules."""

from __future__ import annotations

import re
from collections.abc import Collection

from core.intent_models import Intent, IntentType
from core.intent_system_rules import detect_self_diagnostics, detect_system_health


FULL_SYSTEM_PHRASES = [
    "computer health", "system health", "system status", "computer status",
    "argo status", "argo health", "how is my computer", "how is my computer doing",
    "how's my computer doing", "hows my computer doing", "how is the system",
    "give me a status report", "status report", "full system", "full status",
    "full report", "full system status", "complete status", "everything",
    "all system info", "all system information", "all computer info",
    "all computer information", "everything about my computer",
    "anything wrong with my system", "anything wrong with my computer",
    "is anything wrong with my system", "is anything wrong with my computer",
]
HARDWARE_KEYWORDS = [
    "memory", "ram", "cpu", "processor", "gpu", "graphics", "video card",
    "system specs", "hardware", "motherboard", "mainboard",
]
SYSTEM_MEMORY_QUERIES = [
    "how much memory do i have", "total memory", "installed memory", "ram size", "memory usage",
]
SYSTEM_CPU_QUERIES = [
    "what cpu do i have", "what kind of cpu", "what type of cpu", "what's my cpu",
    "whats my cpu", "cpu model", "cpu name", "what processor do i have",
    "what kind of processor", "what type of processor", "what's my processor",
    "whats my processor", "processor model", "processor name", "which cpu",
    "which processor", "my cpu", "tell me about my cpu", "tell me about my processor",
]
SYSTEM_GPU_QUERIES = [
    "what gpu do i have", "gpu model", "gpu name", "graphics card", "video card", "graphics",
]
SYSTEM_OS_QUERIES = [
    "operating system", "os version", "windows version", "what os",
    "what operating system", "what system am i running", "what system am i on",
    "what os am i running", "which os", "which operating system",
]
SYSTEM_MOTHERBOARD_QUERIES = [
    "what motherboard", "what kind of motherboard", "what type of motherboard",
    "what's my motherboard", "whats my motherboard", "which motherboard",
    "motherboard model", "motherboard name", "my motherboard",
    "tell me about my motherboard", "mainboard", "what mainboard",
]
ARGO_IDENTITY_PHRASES = {
    "who are you", "what are you", "who is argo", "what is argo", "what's your name",
    "what is your name", "tell me about yourself", "tell me about you", "identify yourself",
    "who am i talking to", "who am i speaking to",
}
ARGO_GOVERNANCE_LAW_PHRASES = {
    "argo laws", "what are your laws", "what laws govern you", "what rules do you follow",
    "what policies do you follow", "what are your policies", "what are your rules",
}
ARGO_GOVERNANCE_GATE_PHRASES = {
    "five gates", "hard gates", "argo gates", "safety gates", "permission gates", "execution gates",
}
_HARDWARE_GENERAL_RE = re.compile(
    r"\b(latest|best|newest|buy|buying|recommend|build|building|upgrade|upgrading"
    r"|compare|comparing|vs|versus|review|benchmark|shop|shopping|market|available"
    r"|released|announcement|generation|lineup|should\s+i\s+get|worth|price|cost"
    r"|hotend|printer|3d|filament|nozzle|extruder)\b"
)
SILENCE_PHRASES = frozenset(
    {"shut up", "stop talking", "enough", "ok stop", "okay stop", "quiet", "be quiet"}
)


def parse_control_intent(
    raw_text: str,
    normalized: str,
    serious_mode: bool,
    sleep_phrases: Collection[str],
) -> Intent | None:
    if any(phrase in normalized for phrase in SILENCE_PHRASES):
        return Intent(IntentType.SILENCE_OVERRIDE, 1.0, raw_text, serious_mode=False)
    if (
        normalized in sleep_phrases
        or normalized.startswith("go to sleep")
        or normalized == "sleep"
        or normalized.startswith("sleep ")
    ):
        return Intent(IntentType.SLEEP, 1.0, raw_text, serious_mode=serious_mode)
    if detect_self_diagnostics(normalized):
        return Intent(IntentType.SELF_DIAGNOSTICS, 1.0, raw_text, serious_mode=serious_mode)
    return None


def parse_full_system_status(raw_text: str, normalized: str, serious_mode: bool) -> Intent | None:
    if not any(phrase in normalized for phrase in FULL_SYSTEM_PHRASES):
        return None
    return Intent(IntentType.SYSTEM_STATUS, 1.0, raw_text, serious_mode=serious_mode, subintent="full")


def parse_identity_or_governance(raw_text: str, normalized: str, serious_mode: bool) -> Intent | None:
    if any(phrase in normalized for phrase in ARGO_IDENTITY_PHRASES):
        return Intent(IntentType.ARGO_IDENTITY, 1.0, raw_text, serious_mode=serious_mode)
    law = any(phrase in normalized for phrase in ARGO_GOVERNANCE_LAW_PHRASES) or (
        "law" in normalized and "argo" in normalized
    )
    gate = any(phrase in normalized for phrase in ARGO_GOVERNANCE_GATE_PHRASES) or (
        "gate" in normalized and "argo" in normalized
    )
    if not (law or gate):
        return None
    subintent = "overview" if law and gate else "gates" if gate else "laws"
    return Intent(IntentType.ARGO_GOVERNANCE, 1.0, raw_text, serious_mode=serious_mode, subintent=subintent)


def parse_system_health(raw_text: str, normalized: str, serious_mode: bool) -> Intent | None:
    if _HARDWARE_GENERAL_RE.search(normalized):
        return None
    if any(key in normalized for key in HARDWARE_KEYWORDS) or any(
        query in normalized for query in SYSTEM_OS_QUERIES
    ):
        groups = (
            ("memory", SYSTEM_MEMORY_QUERIES),
            ("cpu", SYSTEM_CPU_QUERIES),
            ("gpu", SYSTEM_GPU_QUERIES),
            ("os", SYSTEM_OS_QUERIES),
            ("motherboard", SYSTEM_MOTHERBOARD_QUERIES),
        )
        subintent = next(
            (name for name, queries in groups if any(query in normalized for query in queries)),
            "hardware",
        )
        return Intent(IntentType.SYSTEM_HEALTH, 1.0, raw_text, serious_mode=serious_mode, subintent=subintent)
    if detect_system_health(normalized):
        return Intent(IntentType.SYSTEM_HEALTH, 1.0, raw_text, serious_mode=serious_mode, subintent=None)
    return None
