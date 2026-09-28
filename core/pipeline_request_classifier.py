"""Deterministic request-kind and text-shape classification."""

from __future__ import annotations

import re
from collections.abc import Callable

from core.intent_models import IntentType


QUESTION_CUES = re.compile(
    r"\b(what|why|how|who|when|where|explain|describe|define|tell|show|what's|whats|why's|hows)\b"
)
QUESTION_START = re.compile(r"^(what|why|how|when|where|who)\b")
HEDGING_WORDS = frozenset(
    {"maybe", "might", "could", "would", "should", "perhaps", "possibly", "guess", "think", "can"}
)
ACTION_VERBS = frozenset(
    {
        "open", "close", "quit", "exit", "shutdown", "shut", "delete", "run", "start", "stop",
        "enable", "disable", "install", "remove", "play", "pause", "resume", "next", "skip",
        "set", "change", "turn", "launch",
    }
)
CONCEPT_TOKENS = frozenset(
    {"system", "file", "pipeline", "manager", "audio", "tts", "stt", "rag", "index", "config", "logs", "llm", "model", "voice", "argo"}
)
QUESTION_WORDS = frozenset(
    {"what", "why", "how", "who", "when", "where", "which", "whose", "whom", "is", "are", "do", "does", "did", "can", "could", "would", "should", "will"}
)
STOP_WORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being", "have", "has",
        "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must",
        "shall", "can", "to", "of", "in", "for", "on", "with", "at", "by", "from", "as", "into",
        "through", "during", "before", "after", "above", "below", "between", "under", "again",
        "further", "then", "once", "and", "but", "or", "nor", "so", "yet", "both", "either",
        "neither", "not", "only", "own", "same", "than", "too", "very", "just", "i", "me", "my",
        "you", "your", "he", "him", "his", "she", "her", "it", "its", "we", "our", "they",
        "their", "this", "that", "these", "those",
    }
)
QUESTION_INTENTS = frozenset(
    {
        IntentType.BLUETOOTH_STATUS,
        IntentType.AUDIO_ROUTING_STATUS,
        IntentType.APP_STATUS,
        IntentType.TIME_STATUS,
        IntentType.WORLD_TIME,
        IntentType.VOLUME_STATUS,
        IntentType.SYSTEM_HEALTH,
        IntentType.SYSTEM_STATUS,
        IntentType.SYSTEM_INFO,
        IntentType.COUNT,
        IntentType.ARGO_IDENTITY,
        IntentType.ARGO_GOVERNANCE,
    }
)
ACTION_INTENTS = frozenset(
    {
        IntentType.AUDIO_ROUTING_CONTROL,
        IntentType.APP_CONTROL,
        IntentType.APP_LAUNCH,
        IntentType.VOLUME_CONTROL,
    }
)


def classify_request_kind(user_text: str) -> str:
    if not user_text or not user_text.strip():
        return "UNKNOWN"
    text = user_text.strip().lower()
    tokens = re.findall(r"\w+", text)
    token_set = set(tokens)
    starts_question = bool(QUESTION_START.match(text))
    ends_question = text.endswith("?")
    has_question_cue = bool(QUESTION_CUES.search(text))
    has_hedge = bool(token_set & HEDGING_WORDS) or text.startswith(
        ("can you", "could you", "would you")
    )
    has_action = bool(token_set & ACTION_VERBS)
    looks_question = starts_question or ends_question or has_question_cue or has_hedge
    if has_action and len(tokens) >= 2 and not looks_question:
        return "ACTION"
    if starts_question or ends_question or has_question_cue:
        return "QUESTION"
    if token_set & CONCEPT_TOKENS and not has_action:
        return "QUESTION"
    return "QUESTION"


def classify_request_type(
    user_text: str,
    intent,
    request_kind: str,
    is_executable_command: Callable[[str], bool],
) -> str:
    if request_kind in {"WRITE_MEMORY", "UNKNOWN"}:
        return request_kind
    if intent is None:
        return request_kind
    intent_type = intent.intent_type
    if intent_type in {
        IntentType.MUSIC, IntentType.MUSIC_STOP, IntentType.MUSIC_NEXT, IntentType.MUSIC_STATUS
    }:
        if request_kind == "ACTION" or is_executable_command(user_text):
            return "ACTION"
    if intent_type == IntentType.BLUETOOTH_CONTROL:
        return "ACTION"
    if intent_type in ACTION_INTENTS:
        return "ACTION"
    if intent_type in QUESTION_INTENTS:
        return "QUESTION"
    return request_kind


def has_interrogative_structure(text: str) -> bool:
    if not text:
        return False
    normalized = text.lower().strip()
    tokens = normalized.split()
    return normalized.endswith("?") or bool(tokens and tokens[0] in QUESTION_WORDS)


def meaningful_tokens(text: str) -> list[str]:
    if not text:
        return []
    return [token for token in re.findall(r"\w+", text.lower()) if token not in STOP_WORDS]


def is_identity_query(text: str) -> bool:
    if not text:
        return False
    normalized = text.lower().strip()
    return any(
        re.search(pattern, normalized)
        for pattern in (
            r"what('?s|\s+is)\s+my\s+name",
            r"do\s+you\s+(know|remember)\s+my\s+name",
            r"who\s+am\s+i",
        )
    )
