"""Pure clarification policy for terse opaque questions."""

from __future__ import annotations

import re
from typing import Callable

from core.pipeline_request_classifier import (
    has_interrogative_structure,
    meaningful_tokens,
)


QUESTION_STRUCTURE = {
    "what",
    "whats",
    "where",
    "when",
    "why",
    "how",
    "who",
    "which",
    "is",
    "are",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "should",
    "will",
    "mean",
    "means",
    "meaning",
    "many",
    "much",
}

KNOWN_SINGLETONS = {
    "argo",
    "ai",
    "api",
    "cpu",
    "date",
    "day",
    "email",
    "gpu",
    "home",
    "light",
    "lights",
    "memory",
    "music",
    "name",
    "ram",
    "status",
    "system",
    "temperature",
    "time",
    "volume",
    "weather",
}

NON_PROPOSITIONAL_FRAGMENTS = (
    r"^huh\??$",
    r"^what\??$",
    r"^uh+\??$",
    r"^um+\??$",
    r"^hmm+\??$",
    r"^erm+\??$",
    r"^i\s+don'?t\s+understand\b",
    r"^i\s+do\s+not\s+understand\b",
    r"^it\s+seems\s+like\s+human\b",
)

IMPERATIVE_VERBS = {
    "give", "tell", "show", "list", "generate", "create", "make", "find",
    "get", "pick", "choose", "suggest", "recommend", "explain", "describe",
    "say", "read", "write", "name", "calculate", "compute",
}

IDENTITY_PATTERNS = (
    r"\bmy name is\b",
    r"\bi am called\b",
    r"\bcall me\b",
    r"\bi like\b",
    r"\bi love\b",
    r"\bi prefer\b",
    r"\bi hate\b",
    r"\bi live in\b",
    r"\bi work at\b",
    r"\bi'm from\b",
    r"\bmy favorite\b",
    r"\bmy birthday is\b",
)


def is_non_propositional_utterance(
    text: str,
    request_kind: str,
    *,
    is_executable_command: Callable[[str], bool],
    has_interrogative: Callable[[str], bool],
) -> bool:
    """Return whether input is an explicit fragment requiring clarification."""
    if not text:
        return True
    lower = text.strip().lower()
    if any(re.match(pattern, lower) for pattern in NON_PROPOSITIONAL_FRAGMENTS):
        return True
    if request_kind == "ACTION":
        return False
    if is_executable_command(lower) or has_interrogative(lower):
        return False
    tokens = lower.split()
    if tokens and tokens[0] in IMPERATIVE_VERBS:
        return False
    if any(re.search(pattern, lower) for pattern in IDENTITY_PATTERNS):
        return False
    return False


def ambiguous_short_question_prompt(
    text: str,
    request_kind: str,
    topic: str | None = None,
) -> str | None:
    """Ask for grounding before answering terse opaque shorthand."""
    if request_kind != "QUESTION" or topic or not has_interrogative_structure(text):
        return None
    meaningful = [
        token for token in meaningful_tokens(text) if token not in QUESTION_STRUCTURE
    ]
    if not meaningful or len(meaningful) > 2:
        return None

    for token in meaningful:
        if token in KNOWN_SINGLETONS:
            continue
        has_alpha = bool(re.search(r"[a-z]", token))
        has_digit = bool(re.search(r"\d", token))
        is_short_code = len(token) <= 4 and has_alpha
        is_mixed_code = len(token) <= 8 and has_alpha and has_digit
        if is_short_code or is_mixed_code:
            return (
                f"When you say '{token}', do you mean something from ARGO or "
                "your setup, or the general meaning?"
            )
    return None
