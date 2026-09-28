"""Pure clarification policy for terse opaque questions."""

from __future__ import annotations

import re

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
