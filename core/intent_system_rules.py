"""Deterministic system intent detectors and text normalization.

This module owns the keyword banks used by these functions so rule data and
behavior cannot drift apart.  core.intent_parser re-exports the public helpers.
"""

from __future__ import annotations

import re

SYSTEM_HEALTH_TRIGGERS = [
    "system health",
    "computer health",
    "system status",
    "computer status",
    "how's my system",
    "hows my system",
    "how is my system",
    "how is my system doing",
    "system check",
    "gpu health",
    "cpu health",
    "system gpu health",
    "system cpu health",
    "disk space",
    "free space",
]

SELF_DIAGNOSTICS_PHRASES = [
    "run diagnostics",
    "check yourself",
    "self check",
    "self-check",
    "selfcheck",
    "are you okay",
    "are you ok",
    "are you working",
    "are you broken",
    "what's wrong with you",
    "whats wrong with you",
    "check your systems",
    "diagnose yourself",
    "argo diagnostics",
    "run self test",
    "self test",
    "health check",
    "check your health",
    "anything wrong",
    "is something wrong",
    "are you having problems",
    "fix yourself",
    "fix your voice",
    "repair yourself",
    "figure out what's wrong and fix it",
    "figure out what is wrong and fix it",
    "what's your status",
    "whats your status",
]

AUDIO_ROUTING_KEYWORDS = [
    "audio",
    "sound",
    "speaker",
    "speakers",
    "headphones",
    "headset",
    "mic",
    "microphone",
    "output",
    "input",
]

SYSTEM_KEYWORDS = {
    "how much memory do i have",
    "total memory",
    "installed memory",
    "ram size",
    "what cpu do i have",
    "cpu model",
    "cpu name",
    "what processor do i have",
    "processor model",
    "processor name",
    "what gpu do i have",
    "gpu model",
    "gpu name",
    "graphics card",
    "video card",
    "graphics",
    "system specs",
    "hardware",
    "operating system",
    "os version",
    "windows version",
    "what os",
    "what operating system",
    "gpu health",
    "cpu health",
    "system health",
    "system status",
    "computer status",
    "disk space",
    "free space",
    "memory usage",
    "how much space do i have",
    "which drive has the most free space",
    "what drive is the fullest",
}

SYSTEM_NORMALIZE = {
    "gpu health": "system gpu health",
    "cpu health": "system cpu health",
    "disk": "disk space",
}

TEMP_KEYWORDS = [
    "temperature",
    "temp",
    "hot",
    "overheating",
    "heat",
    "thermal",
    "thermals",
]

DISK_QUERY_PHRASES = [
    "drive",
    "drives",
    "disk",
    "disks",
    "free space",
    "disk space",
    "storage",
    "fullest",
    "most free",
    "most space",
    "how much space",
]

def detect_system_health(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in SYSTEM_HEALTH_TRIGGERS)


def detect_self_diagnostics(text: str) -> bool:
    """Detect ARGO self-check / diagnostics requests (Phase 1)."""
    t = text.lower()
    # Scope new symptom-based requests to ARGO, not someone else's broken app.
    symptom = re.search(r"\b(your (?:thing|voice|audio|microphone|code|system)|you|yourself|argo)\b", t)
    broken = re.search(r"\b(not working|isn't working|is not working|broken|fix|repair|no sound)\b", t)
    return bool(symptom and broken) or t.strip() in ("diagnose and fix", "diagnose and fix it") or any(p in t for p in SELF_DIAGNOSTICS_PHRASES)


def detect_hardware_info(text: str) -> bool:
    """Detect hardware identification queries: what CPU/GPU/RAM do I have."""
    t = text.lower()
    # Must have an identification phrase
    id_phrases = [
        "what kind of", "what type of", "what is my", "what's my", "whats my",
        "which", "do i have", "have i got", "tell me about my", "specs",
        "specifications", "what cpu", "what gpu", "what processor", "what graphics",
    ]
    hw_keywords = ["cpu", "processor", "gpu", "graphics card", "video card", "ram", "memory", "hardware"]
    
    has_id = any(p in t for p in id_phrases)
    has_hw = any(k in t for k in hw_keywords)
    
    # "specs" or "specifications" alone is enough
    if "specs" in t or "specification" in t:
        return True
    
    return has_id and has_hw


def detect_temperature_query(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in TEMP_KEYWORDS)


def detect_disk_query(text: str) -> bool:
    t = text.lower()
    if re.search(r"\b[a-z]\s*drive\b", t):
        return True
    if re.search(r"\b[a-z]:\b", t):
        return True
    return any(k in t for k in DISK_QUERY_PHRASES)


def normalize_system_text(text: str) -> str:
    t = text.lower().strip()
    return SYSTEM_NORMALIZE.get(t, t)


def normalize_status_text(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text.lower().strip())
    politeness_prefixes = [
        "can you please",
        "could you please",
        "would you please",
        "please could you",
        "please can you",
        "please would you",
        "hey can you",
        "hey could you",
        "hey please",
        "can you",
        "could you",
        "would you",
        "please",
        "tell me",
        "give me",
        "show me",
        "hey",
        "a",
        "an",
        "the",
    ]
    changed = True
    while changed:
        changed = False
        for prefix in politeness_prefixes:
            if t == prefix:
                t = ""
                changed = True
                break
            if t.startswith(prefix + " "):
                t = t[len(prefix):].strip()
                changed = True
                break
    t = re.sub(r"\s+", " ", t).strip()
    return t


def normalize_audio_routing_text(text: str) -> str:
    if not text:
        return ""
    lowered = re.sub(r"\s+", " ", text.lower().strip())
    if not any(kw in lowered for kw in AUDIO_ROUTING_KEYWORDS):
        return lowered
    politeness_prefixes = [
        "can you please",
        "could you please",
        "would you please",
        "please could you",
        "please can you",
        "please would you",
        "hey can you",
        "hey could you",
        "hey please",
        "can you",
        "could you",
        "would you",
        "please",
        "tell me",
        "show me",
        "hey",
    ]
    for prefix in politeness_prefixes:
        if lowered == prefix:
            return ""
        if lowered.startswith(prefix + " "):
            lowered = lowered[len(prefix):].strip()
            break
    return re.sub(r"\s+", " ", lowered).strip()


def normalize_app_text(text: str) -> str:
    if not text:
        return ""
    lowered = re.sub(r"\s+", " ", text.lower().strip())
    politeness_prefixes = [
        "can you please",
        "could you please",
        "would you please",
        "please could you",
        "please can you",
        "please would you",
        "can you",
        "could you",
        "would you",
        "please",
        "hey",
        "tell me",
    ]
    for prefix in politeness_prefixes:
        if lowered == prefix:
            return ""
        if lowered.startswith(prefix + " "):
            lowered = lowered[len(prefix):].strip()
            break
    return re.sub(r"\s+", " ", lowered).strip()


def is_system_keyword(text: str) -> bool:
    t = text.lower().strip()
    return t in SYSTEM_KEYWORDS or detect_disk_query(t)
