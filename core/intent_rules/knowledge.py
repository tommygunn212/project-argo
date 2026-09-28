"""Priority knowledge-domain rules that run before generic questions."""

from __future__ import annotations

from core.intent_models import Intent, IntentType


PHYSICS_KEYWORDS = (
    "cool down", "heat", "thermodynamics", "physics", "temperature", "energy",
    "conduction", "convection", "radiation", "molecule", "evaporation",
    "why does.*cool", "how does.*cool",
)
FINANCE_KEYWORDS = (
    "bitcoin", "money", "currency", "finance", "dollar", "crypto", "blockchain",
    "stock", "bond", "investment", "is bitcoin.*money", "what is.*bitcoin",
)
TIME_SYSTEM_KEYWORDS = (
    "what time", "current time", "system status", "system doing", "system health",
    "status report", "how's my system", "system info", "uptime", "cpu usage",
    "memory usage", "disk usage",
)


def parse_knowledge_intent(raw_text: str, normalized: str, serious_mode: bool) -> Intent | None:
    if any(keyword in normalized for keyword in PHYSICS_KEYWORDS) or (
        "cool" in normalized and "why" in normalized
    ):
        intent_type = IntentType.KNOWLEDGE_PHYSICS
    elif any(keyword in normalized for keyword in FINANCE_KEYWORDS):
        intent_type = IntentType.KNOWLEDGE_FINANCE
    elif any(keyword in normalized for keyword in TIME_SYSTEM_KEYWORDS):
        intent_type = IntentType.KNOWLEDGE_TIME_SYSTEM
    else:
        return None
    return Intent(intent_type, 1.0, raw_text, serious_mode=serious_mode)
