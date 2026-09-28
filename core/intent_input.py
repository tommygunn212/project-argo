"""Deterministic input preparation for rule-based intent parsing."""

from __future__ import annotations

from dataclasses import dataclass
import re

from core.intent_system_rules import (
    normalize_app_text,
    normalize_audio_routing_text,
    normalize_status_text,
    normalize_system_text,
)


PHONETIC_FIXES = {
    "porcupine": "argo",
    "pocket point": "argo",
    "pocketpoint": "argo",
    "led like": "led light",
    "ducts": "ducks",
}


def normalize_phrase(text: str) -> str:
    return (
        text.strip().lower()
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
    )


def normalize_for_rules(raw_text: str) -> str:
    normalized = normalize_system_text(raw_text.lower())
    normalized = normalize_status_text(normalized)
    normalized = normalize_audio_routing_text(normalized)
    normalized = normalize_app_text(normalized)
    normalized = normalize_phrase(normalized)
    return normalized.replace("sound", "volume").replace("loudness", "volume")


def apply_phonetic_fixes(normalized: str) -> str:
    for mistake, replacement in PHONETIC_FIXES.items():
        normalized = normalized.replace(mistake, replacement)
    return normalized


@dataclass(frozen=True)
class PreparedIntentText:
    original: str
    normalized: str
    tokens: tuple[str, ...]
    first_word: str


def strip_wake_prefix(raw_text: str, normalized: str) -> PreparedIntentText:
    normalized = re.sub(r"^(argo[\s,]+)+", "", normalized).strip()
    original = re.sub(
        r"^(argo[\s,]+)+", "", raw_text, flags=re.IGNORECASE
    ).strip()
    tokens = tuple(re.findall(r"[a-z0-9']+", normalized))
    return PreparedIntentText(original, normalized, tokens, tokens[0] if tokens else "")
